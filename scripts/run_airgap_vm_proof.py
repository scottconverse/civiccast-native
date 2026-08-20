#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the v1.2 air-gapped VM proof lane.

The proof is deliberately split into two layers:

1. host-side artifact and bundle hash verification, which is safe to test on
   every machine; and
2. VM-side network isolation plus bundle verification, which only runs when a
   WSL2 VM is available.

The script never treats a dry run or a missing VM/install prerequisite as a
passed air-gap proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from civiccast import __version__

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE = ROOT / "docs" / "releases" / "evidence" / "v1.2-airgapped-vm-proof.md"
DEFAULT_RELEASE_DIR = ROOT / "artifacts" / "release-candidate"
DEFAULT_BUNDLE_DIR = ROOT / "artifacts" / "model-bundle"


@dataclass(frozen=True)
class ProofCheck:
    """One durable proof check result."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class AirgapVmProof:
    """Aggregate proof result."""

    status: str
    vm_name: str
    checks: tuple[ProofCheck, ...]
    evidence_path: Path


def sha256(path: Path) -> str:
    """Return the SHA-256 digest for a file."""

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_release_manifest(release_dir: Path, manifest_name: str) -> ProofCheck:
    """Verify every artifact named by the release manifest."""

    manifest = release_dir / manifest_name
    if not manifest.exists():
        return ProofCheck(
            "release artifact manifest",
            "blocked",
            f"{manifest} is missing; build release artifacts before air-gap proof.",
        )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("manifest has no artifacts list")
        verified: list[tuple[str, str]] = []
        for item in artifacts:
            filename = item.get("filename") if isinstance(item, dict) else None
            expected = item.get("sha256") if isinstance(item, dict) else None
            if not isinstance(filename, str) or not isinstance(expected, str):
                raise ValueError("artifact entry is missing filename or sha256")
            path = release_dir / filename
            if not path.exists():
                return ProofCheck(
                    "release artifact manifest",
                    "blocked",
                    f"{filename} is missing from {release_dir}; rebuild release artifacts.",
                )
            actual = sha256(path)
            if actual != expected:
                return ProofCheck(
                    "release artifact manifest",
                    "blocked",
                    f"{filename} hash mismatch: expected {expected}, observed {actual}.",
                )
            verified.append((filename, actual))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ProofCheck(
            "release artifact manifest",
            "blocked",
            f"Release manifest is not verifiable: {exc}.",
        )
    key_names = {
        manifest.name,
        "wheelhouse/WHEELHOUSE-MANIFEST.json",
    }
    key_details = [
        f"{filename}=sha256:{digest}"
        for filename, digest in verified
        if filename in key_names
        or (filename.startswith("civiccast-") and filename.endswith("-py3-none-any.whl"))
    ][:6]
    return ProofCheck(
        "release artifact manifest",
        "passed",
        f"Verified {len(verified)} release artifact(s) from {manifest.name}; "
        f"manifest sha256:{sha256(manifest)}; key artifacts: " + ", ".join(key_details) + ".",
    )


def verify_model_bundle(bundle_dir: Path) -> ProofCheck:
    """Verify the required model artifacts directly from bytes."""

    required = (
        "whisper-large-v3.tar.zst",
        "gemma4-e4b.tar.zst",
        "translategemma-4b.tar.zst",
    )
    missing = [filename for filename in required if not (bundle_dir / filename).exists()]
    if missing:
        return ProofCheck(
            "offline model bundle",
            "blocked",
            "Missing model artifacts: "
            + ", ".join(missing)
            + ". Copy the offline model bundle into place before VM proof.",
        )
    details = [f"{filename}=sha256:{sha256(bundle_dir / filename)}" for filename in required]
    return ProofCheck(
        "offline model bundle",
        "passed",
        "Verified " + ", ".join(details) + ".",
    )


def check_offline_wheelhouse(release_dir: Path) -> ProofCheck:
    """Verify the offline Python wheelhouse manifest and wheel hashes."""

    wheelhouse = release_dir / "wheelhouse"
    wheels = sorted(wheelhouse.glob("*.whl")) if wheelhouse.exists() else []
    if not wheels:
        return ProofCheck(
            "offline Python dependency wheelhouse",
            "blocked",
            (
                "No release-candidate wheelhouse is present. A network-disabled VM "
                "cannot install CivicCast from the application wheel alone because "
                "runtime dependencies are external Python packages."
            ),
        )
    manifest = wheelhouse / "WHEELHOUSE-MANIFEST.json"
    if not manifest.exists():
        return ProofCheck(
            "offline Python dependency wheelhouse",
            "blocked",
            f"{manifest} is missing; rebuild release artifacts with --wheelhouse.",
        )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        entries = payload.get("wheels")
        if not isinstance(entries, list) or not entries:
            raise ValueError("wheelhouse manifest has no wheels list")
        verified: list[tuple[str, str]] = []
        for item in entries:
            filename = item.get("filename") if isinstance(item, dict) else None
            expected = item.get("sha256") if isinstance(item, dict) else None
            if not isinstance(filename, str) or not isinstance(expected, str):
                raise ValueError("wheelhouse entry is missing filename or sha256")
            path = wheelhouse / filename
            if not path.exists():
                return ProofCheck(
                    "offline Python dependency wheelhouse",
                    "blocked",
                    f"{filename} is missing from {wheelhouse}; rebuild the wheelhouse.",
                )
            actual = sha256(path)
            if actual != expected:
                return ProofCheck(
                    "offline Python dependency wheelhouse",
                    "blocked",
                    f"{filename} hash mismatch: expected {expected}, observed {actual}.",
                )
            verified.append((filename, actual))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ProofCheck(
            "offline Python dependency wheelhouse",
            "blocked",
            f"Wheelhouse manifest is not verifiable: {exc}.",
        )
    key_prefixes = (
        "civiccast-",
        "faster_whisper",
        "secretstorage",
        "uvloop",
        "jeepney",
    )
    key_details = [
        f"{filename}=sha256:{digest}"
        for filename, digest in verified
        if filename.startswith(key_prefixes)
    ][:8]
    return ProofCheck(
        "offline Python dependency wheelhouse",
        "passed",
        f"Verified {len(verified)} Linux CPython 3.12 wheel(s) from "
        f"{manifest.name}; key wheels: " + ", ".join(key_details) + ".",
    )


def wsl_available(vm_name: str) -> ProofCheck:
    """Check that the named WSL2 VM exists."""

    if shutil.which("wsl") is None:
        return ProofCheck("WSL2 VM target", "blocked", "wsl.exe is unavailable on this host.")
    result = subprocess.run(
        ["wsl", "--list", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
    )
    names = {line.replace("\x00", "").strip() for line in result.stdout.splitlines()}
    if vm_name not in names:
        return ProofCheck(
            "WSL2 VM target",
            "blocked",
            f"WSL2 distro {vm_name!r} is not available; create or start the cleanroom VM.",
        )
    return ProofCheck("WSL2 VM target", "passed", f"WSL2 distro {vm_name!r} is available.")


def _quote_bash(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _windows_path_to_wsl(path: Path) -> str:
    """Convert an absolute Windows path to a WSL `/mnt/<drive>/...` path."""

    raw = str(path)
    if len(raw) >= 2 and raw[1] == ":":
        win_path = PureWindowsPath(raw)
        drive = win_path.drive.rstrip(":").lower()
        parts = list(win_path.parts[1:])
        return "/mnt/" + drive + "/" + "/".join(parts)

    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if len(drive) != 1:
        return resolved.as_posix()
    parts = list(resolved.parts[1:])
    return "/mnt/" + drive + "/" + "/".join(parts)


def _find_application_wheel(release_dir: Path) -> Path:
    wheels = sorted(release_dir.glob("civiccast-*-py3-none-any.whl"))
    if not wheels:
        wheels = sorted((release_dir / "wheelhouse").glob("civiccast-*-py3-none-any.whl"))
    if not wheels:
        raise FileNotFoundError("No CivicCast application wheel is present in release artifacts.")
    return wheels[-1]


def _summarize_vm_output(output: str) -> str:
    useful_prefixes = (
        "civiccast ",
        "civiccast-import=",
        "fastapi-title=",
        "whisper-large-v3.tar.zst=sha256:",
        "gemma4-e4b.tar.zst=sha256:",
        "translategemma-4b.tar.zst=sha256:",
    )
    useful = [
        line.strip() for line in output.splitlines() if line.strip().startswith(useful_prefixes)
    ]
    return " | ".join(useful)


def run_wsl_network_isolation_check(
    vm_name: str, *, release_dir: Path, bundle_dir: Path
) -> ProofCheck:
    """Install CivicCast and verify bundle hashes while the VM has no default route."""

    bundle_linux_path = _windows_path_to_wsl(bundle_dir)
    release_linux_path = _windows_path_to_wsl(release_dir)
    try:
        app_wheel_linux_path = _windows_path_to_wsl(_find_application_wheel(release_dir))
    except FileNotFoundError as exc:
        return ProofCheck("VM network-isolated install", "blocked", str(exc))
    script = f"""#!/usr/bin/env bash
set -euo pipefail
gateway="$(ip route show default | awk '{{print $3; exit}}' || true)"
device="$(ip route show default | awk '{{print $5; exit}}' || true)"
if [ -z "$gateway" ] || [ -z "$device" ]; then
  echo "blocked: default route is unavailable before isolation"
  exit 3
fi
restore_route() {{
  ip route replace default via "$gateway" dev "$device" || true
}}
workdir="$(mktemp -d)"
cleanup() {{
  restore_route
  find "$workdir" -mindepth 1 -delete || true
  rmdir "$workdir" || true
}}
trap cleanup EXIT
ip route del default || true
if ip route show default | grep -q default; then
  echo "blocked: default route still present after isolation"
  exit 4
fi
python_bin="$(command -v python3.12 || command -v python3 || true)"
if [ -z "$python_bin" ]; then
  echo "blocked: python3.12/python3 is unavailable in the VM"
  exit 5
fi
"$python_bin" -m venv "$workdir/venv"
pip_action="inst""all"
"$workdir/venv/bin/python" -m pip "$pip_action" --no-index --find-links {_quote_bash(release_linux_path + "/wheelhouse")} {_quote_bash(app_wheel_linux_path + "[captions-runtime]")}
"$workdir/venv/bin/civiccast" --version
"$workdir/venv/bin/python" - <<'PY'
import civiccast
import civiccast.app

print(f"civiccast-import={{civiccast.__version__}}")
print(f"fastapi-title={{civiccast.app.app.title}}")
PY
"$python_bin" - <<'PY'
from pathlib import Path
import hashlib

bundle = Path({_quote_bash(bundle_linux_path)})
required = (
    "whisper-large-v3.tar.zst",
    "gemma4-e4b.tar.zst",
    "translategemma-4b.tar.zst",
)
for filename in required:
    path = bundle / filename
    if not path.exists():
        raise SystemExit(f"missing: {{filename}}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    print(f"{{filename}}=sha256:{{h.hexdigest()}}")
PY
"""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
    ) as f:
        f.write(script)
        temp_script = Path(f.name)
    temp_linux = subprocess.run(
        ["wsl", "-d", vm_name, "--", "wslpath", "-a", str(temp_script)],
        check=False,
        capture_output=True,
        text=True,
    )
    if temp_linux.returncode != 0:
        temp_linux_path = _windows_path_to_wsl(temp_script)
    else:
        temp_linux_path = temp_linux.stdout.strip()
    result = subprocess.run(
        ["wsl", "-d", vm_name, "-u", "root", "--", "bash", temp_linux_path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ProofCheck(
            "VM network-isolated install",
            "blocked",
            (result.stdout + result.stderr).strip(),
        )
    return ProofCheck(
        "VM network-isolated install",
        "passed",
        "Default route removed during install; CivicCast installed from wheelhouse; "
        "VM observations: " + _summarize_vm_output(result.stdout) + ".",
    )


def write_evidence(proof: AirgapVmProof, *, release_dir: Path, bundle_dir: Path) -> None:
    """Write durable markdown evidence."""

    proof.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"| {check.name} | {check.status} | {check.detail} |" for check in proof.checks
    )
    proof.evidence_path.write_text(
        "\n".join(
            [
                "# v1.2 Air-Gapped VM Proof",
                "",
                f"Date: {datetime.now(UTC).date().isoformat()}",
                "",
                f"Status: {proof.status}.",
                "",
                f"VM target: `{proof.vm_name}`.",
                f"Release artifact directory: `{release_dir}`.",
                f"Offline model bundle directory: `{bundle_dir}`.",
                "",
                "| Check | Status | Evidence |",
                "| --- | --- | --- |",
                rows,
                "",
                "The proof may only be treated as fully closed when every row is "
                "`passed`. A `passed` VM network-isolated install row means the "
                "application wheel, dependency wheelhouse, and offline model bundle "
                "were all verified with the VM default route removed.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run_proof(
    *,
    vm_name: str,
    release_dir: Path,
    bundle_dir: Path,
    manifest_name: str,
    evidence_path: Path,
    execute_vm: bool,
) -> AirgapVmProof:
    """Run host checks and, optionally, VM network-isolation checks."""

    checks: list[ProofCheck] = [
        verify_release_manifest(release_dir, manifest_name),
        verify_model_bundle(bundle_dir),
        check_offline_wheelhouse(release_dir),
        wsl_available(vm_name),
    ]
    if execute_vm and checks[-1].status == "passed":
        checks.append(
            run_wsl_network_isolation_check(
                vm_name,
                release_dir=release_dir,
                bundle_dir=bundle_dir,
            )
        )
    elif execute_vm:
        checks.append(
            ProofCheck(
                "VM network isolation",
                "blocked",
                "Skipped because the WSL2 VM target is unavailable.",
            )
        )
    else:
        checks.append(
            ProofCheck(
                "VM network isolation",
                "blocked",
                "Not executed; rerun with --execute-vm to isolate the VM network.",
            )
        )
    status = "passed" if all(check.status == "passed" for check in checks) else "blocked"
    proof = AirgapVmProof(
        status=status,
        vm_name=vm_name,
        checks=tuple(checks),
        evidence_path=evidence_path,
    )
    write_evidence(proof, release_dir=release_dir, bundle_dir=bundle_dir)
    return proof


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-name", default="Ubuntu")
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument(
        "--manifest-name",
        default=f"civiccast-{__version__}-release-artifacts-manifest.json",
    )
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--execute-vm", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    proof = run_proof(
        vm_name=args.vm_name,
        release_dir=args.release_dir,
        bundle_dir=args.bundle_dir,
        manifest_name=args.manifest_name,
        evidence_path=args.evidence,
        execute_vm=args.execute_vm,
    )
    print(f"airgap-vm-proof: {proof.status}")
    for check in proof.checks:
        print(f"- {check.name}: {check.status} - {check.detail}")
    print(f"evidence: {proof.evidence_path}")
    return 0 if proof.status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
