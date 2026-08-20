#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build CivicCast release-candidate artifacts.

This script intentionally separates artifact construction from release
publication. It can run on a branch without creating or moving tags.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from civiccast import __version__
from civiccast.installer.models import ModelBundleRequest
from civiccast.installer.service import build_model_bundle_manifest

ROOT = Path(__file__).resolve().parent.parent
try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT / "scripts"))
    from collect_source_state import collect_source_state

DEFAULT_OUT = ROOT / "artifacts" / "release"
LINUX_WHEELHOUSE_MARKER_REQUIREMENTS = (
    # Exporting from a Windows host evaluates sys_platform markers locally, so
    # Linux-only runtime dependencies need an explicit second download pass for
    # the WSL2/air-gapped install target.
    "jeepney==0.9.0",
    "SecretStorage==3.5.0",
    "uvloop==0.22.1",
)


@dataclass(frozen=True)
class Artifact:
    path: Path
    kind: str


def _run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pe_has_authenticode_evidence(path: Path) -> bool:
    """True if a PE file carries embedded Authenticode evidence (a non-empty
    Certificate Table, data directory index 4). Reads the real bytes so the
    recorded signing state cannot drift from the artifact — never a flag. Full
    chain/timestamp validity is enforced separately by the CI
    Get-AuthenticodeSignature fail-closed step (see release-artifacts.yml)."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    if len(data) < e_lfanew + 24 or data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        return False
    opt = e_lfanew + 24
    magic = int.from_bytes(data[opt : opt + 2], "little")
    if magic == 0x10B:  # PE32
        dd_start = opt + 96
    elif magic == 0x20B:  # PE32+
        dd_start = opt + 112
    else:
        return False
    cert_entry = dd_start + 4 * 8  # data directory index 4 = Certificate Table
    if len(data) < cert_entry + 8:
        return False
    cert_size = int.from_bytes(data[cert_entry + 4 : cert_entry + 8], "little")
    return cert_size > 0


def _validate_gstreamer_runtime_archive(archive: Path, checksum: Path) -> None:
    expected = checksum.read_text(encoding="utf-8").split()[0].strip().lower()
    actual = _sha256(archive)
    if actual != expected:
        raise RuntimeError(
            "Bundled CivicCast GStreamer runtime failed SHA-256 verification "
            f"(expected {expected}, got {actual})."
        )

    required_members = {
        "gstreamer/bin/gst-inspect-1.0",
        "gstreamer/lib/x86_64-linux-gnu/gstreamer-1.0/libgstrsclosedcaption.so",
        "gstreamer/libexec/gstreamer-1.0/gst-plugin-scanner",
    }
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = {member.name for member in tar.getmembers() if member.isfile()}
    except tarfile.TarError as exc:
        raise RuntimeError(
            f"Bundled CivicCast GStreamer runtime is not a valid gzip tar archive: {archive}"
        ) from exc

    missing = sorted(required_members - names)
    if missing:
        raise RuntimeError(
            "Bundled CivicCast GStreamer runtime archive is missing required files: "
            + ", ".join(missing)
        )


def _git_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


SOURCE_ARCHIVE_EXCLUDED_ROOTS = {
    ".agent-runs",
    "audit-team-report",
    "audit-walkthrough",
    "docs/releases/evidence",
    "tester-handoff",
}


def _source_archive_excludes(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(
        rel == excluded or rel.startswith(f"{excluded}/")
        for excluded in SOURCE_ARCHIVE_EXCLUDED_ROOTS
    )


def build_source_archive(out_dir: Path, version: str) -> Artifact:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"civiccast-{version}-source.tar.gz"
    prefix = f"civiccast-{version}/"
    with tarfile.open(target, "w:gz") as tar:
        for path in _git_files():
            if _source_archive_excludes(path):
                continue
            if not path.exists():
                raise FileNotFoundError(
                    "Tracked source file is missing and cannot be archived: "
                    f"{path.relative_to(ROOT).as_posix()}"
                )
            tar.add(path, arcname=prefix + path.relative_to(ROOT).as_posix())
    return Artifact(target, "source-tarball")


def build_python_artifacts(out_dir: Path) -> list[Artifact]:
    dist_dir = out_dir
    dist_dir.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in dist_dir.iterdir() if path.is_file()}
    _run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)])
    built = [
        path
        for path in sorted(dist_dir.iterdir())
        if path.is_file() and path.resolve() not in before
    ]
    return [Artifact(path, "python-package") for path in built]


def _is_civiccast_wheel(path: Path) -> bool:
    return path.name.startswith("civiccast-") and path.name.endswith("-py3-none-any.whl")


def _wheel_version_matches(path: Path, version: str) -> bool:
    wheel_version = path.name.removeprefix("civiccast-").removesuffix("-py3-none-any.whl")
    try:
        return Version(wheel_version) == Version(version)
    except InvalidVersion:
        return False


def _uv_command() -> list[str]:
    local_uv = ROOT / ".venv" / "Scripts" / "uv.exe"
    if local_uv.exists():
        return [str(local_uv)]
    found = shutil.which("uv")
    if found:
        return [found]
    return [sys.executable, "-m", "uv"]


def _npm_command() -> list[str]:
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return [found]
    raise RuntimeError("npm is required to build the Windows Tauri installer")


def _python_with_pip_command() -> list[str]:
    candidates: list[list[str]] = [[sys.executable]]
    for candidate in ("python", "python3"):
        found = shutil.which(candidate)
        if found:
            candidates.append([found])
    py_launcher = shutil.which("py")
    if py_launcher:
        candidates.extend([[py_launcher, "-3.12"], [py_launcher, "-3"]])

    seen: set[tuple[str, ...]] = set()
    for command in candidates:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        probe = subprocess.run(
            [*command, "-m", "pip", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return command
    raise RuntimeError("Python with pip is required to build the release wheelhouse")


def build_python_wheelhouse(out_dir: Path, version: str) -> Artifact:
    """Build a hash-manifested Linux x64 dependency wheelhouse.

    The air-gapped proof installs inside WSL2 Linux, so the wheelhouse must
    contain Linux-compatible wheels rather than whatever wheels the developer
    host would naturally download.
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale_wheel in out_dir.glob("civiccast-*-py3-none-any.whl"):
        stale_wheel.unlink()
    built = build_python_artifacts(out_dir)
    app_wheels = sorted(artifact.path for artifact in built if _is_civiccast_wheel(artifact.path))
    if not app_wheels:
        app_wheels = sorted(
            path
            for path in out_dir.glob("civiccast-*-py3-none-any.whl")
            if _is_civiccast_wheel(path)
        )
    if not app_wheels:
        raise RuntimeError(f"application wheel for CivicCast {version} was not produced")
    if not any(_wheel_version_matches(path, version) for path in app_wheels):
        wheel_names = ", ".join(path.name for path in app_wheels)
        raise RuntimeError(
            f"application wheel for CivicCast {version} was not produced; found {wheel_names}"
        )
    app_wheel = next(path for path in app_wheels if _wheel_version_matches(path, version))

    wheelhouse = out_dir / "wheelhouse"
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True)
    shutil.copy2(app_wheel, wheelhouse / app_wheel.name)

    with tempfile.TemporaryDirectory(prefix="civiccast-wheelhouse-") as temp:
        requirements = Path(temp) / "requirements.txt"
        _run(
            [
                *_uv_command(),
                "export",
                "--format",
                "requirements.txt",
                "--frozen",
                "--no-dev",
                "--extra",
                "captions-runtime",
                "--no-emit-project",
                "--no-hashes",
                "--output-file",
                str(requirements),
            ]
        )
        shutil.copy2(requirements, wheelhouse / "requirements.txt")
        _run(
            [
                *_python_with_pip_command(),
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheelhouse),
                "--requirement",
                str(requirements),
                "--only-binary",
                ":all:",
                "--platform",
                "manylinux2014_x86_64",
                "--platform",
                "manylinux_2_28_x86_64",
                "--platform",
                "manylinux_2_17_x86_64",
                "--python-version",
                "312",
                "--implementation",
                "cp",
                "--abi",
                "cp312",
            ]
        )
        linux_requirements = Path(temp) / "linux-marker-requirements.txt"
        linux_requirements.write_text(
            "\n".join(LINUX_WHEELHOUSE_MARKER_REQUIREMENTS) + "\n",
            encoding="utf-8",
        )
        _run(
            [
                *_python_with_pip_command(),
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheelhouse),
                "--requirement",
                str(linux_requirements),
                "--only-binary",
                ":all:",
                "--platform",
                "manylinux2014_x86_64",
                "--platform",
                "manylinux_2_28_x86_64",
                "--platform",
                "manylinux_2_17_x86_64",
                "--python-version",
                "312",
                "--implementation",
                "cp",
                "--abi",
                "cp312",
            ]
        )

    wheels = sorted(wheelhouse.glob("*.whl"))
    if len(wheels) < 2:
        raise RuntimeError("wheelhouse contains the application wheel but no dependency wheels")
    payload = {
        "version": version,
        "target": "linux-x64-cpython-3.12",
        "install_command": (
            "python -m pip install --no-index --find-links wheelhouse "
            f"'wheelhouse/{app_wheel.name}[captions-runtime]'"
        ),
        "wheels": [
            {
                "filename": path.name,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path in wheels
        ],
    }
    manifest = wheelhouse / "WHEELHOUSE-MANIFEST.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Artifact(manifest, "python-wheelhouse-manifest")


def build_model_manifest(out_dir: Path, version: str) -> Artifact:
    manifest = build_model_bundle_manifest(ModelBundleRequest(profile="public-meetings"))
    payload = manifest.model_dump(mode="json")
    payload["civiccast_version"] = version
    payload["generated_by"] = "scripts/build_release_artifacts.py"
    target = out_dir / f"civiccast-{version}-model-bundle-manifest.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Artifact(target, "model-bundle-manifest")


def build_pkg(out_dir: Path, version: str) -> Artifact:
    if shutil.which("pkgbuild") is None:
        raise RuntimeError("pkgbuild is required for the macOS .pkg artifact")
    root = out_dir / "_pkgroot"
    if root.exists():
        shutil.rmtree(root)
    bindir = root / "usr" / "local" / "bin"
    docdir = root / "usr" / "local" / "share" / "civiccast"
    bindir.mkdir(parents=True)
    docdir.mkdir(parents=True)
    wrapper = bindir / "civiccast"
    wrapper.write_text('#!/usr/bin/env sh\npython3 -m civiccast.cli "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    shutil.copy2(ROOT / "README.md", docdir / "README.md")
    shutil.copy2(ROOT / "docs" / "USER-MANUAL.md", docdir / "USER-MANUAL.md")
    target = out_dir / f"civiccast-{version}.pkg"
    _run(
        [
            "pkgbuild",
            "--root",
            str(root),
            "--identifier",
            "org.civiccast.civiccast",
            "--version",
            version,
            "--install-location",
            "/",
            str(target),
        ]
    )
    shutil.rmtree(root)
    return Artifact(target, "macos-package")


def build_windows_tauri_installer(
    out_dir: Path, version: str, *, reuse_existing: bool = False
) -> Artifact:
    """Build and copy the Windows Tauri setup installer.

    This function never creates placeholder bytes. It runs the installer app's
    native bundle build and then copies the produced setup executable into the release
    artifact directory.

    With ``reuse_existing`` the Tauri build is skipped and the installer .exe
    already in ``out_dir`` is reused. This lets the sidecar (and the downstream
    tester/proof-kit/manifest built by the caller) be regenerated AFTER the .exe
    has been Authenticode-signed, so every checksum describes the signed binary
    (issue #253). It never rebuilds and never rewrites the signed bytes.
    """

    target = out_dir / f"civiccast-{version}-windows-setup.exe"
    if reuse_existing:
        if not target.exists() or target.stat().st_size == 0:
            raise RuntimeError(f"--reuse-installer-exe set but no built installer at {target}")
        _installer_artifact_entry(
            out_dir,
            target,
            kind="windows-tauri-installer",
            package_kind="windows-tauri-exe",
            service_manager="windows-scm",
        )
        return Artifact(target, "windows-tauri-installer")

    installer_dir = ROOT / "civiccast" / "apps" / "installer"
    tauri_dir = installer_dir / "src-tauri"
    if sys.platform != "win32":
        raise RuntimeError("Windows Tauri installer artifact must be built on Windows")
    if not tauri_dir.exists():
        raise RuntimeError("Tauri installer source directory is missing")

    try:
        _prepare_tauri_resources(out_dir, version)
        with _temporary_tauri_release_version(installer_dir, version):
            _run([*_npm_command(), "run", "tauri:build"], cwd=installer_dir)
    finally:
        _clean_tauri_resources()
    target_root = Path(os.environ.get("CARGO_TARGET_DIR", tauri_dir / "target"))
    bundle_dir = target_root / "release" / "bundle" / "nsis"
    candidates = sorted(bundle_dir.glob(f"*_{version}_x64-setup.exe"))
    built = (
        candidates[-1]
        if candidates
        else bundle_dir / f"CivicCast Installer_{version}_x64-setup.exe"
    )
    if not built.exists() or built.stat().st_size == 0:
        raise RuntimeError(f"Tauri build did not produce a non-empty setup executable: {built}")

    shutil.copy2(built, target)
    _installer_artifact_entry(
        out_dir,
        target,
        kind="windows-tauri-installer",
        package_kind="windows-tauri-exe",
        service_manager="windows-scm",
    )
    return Artifact(target, "windows-tauri-installer")


@contextlib.contextmanager
def _temporary_tauri_release_version(installer_dir: Path, version: str):
    """Align Tauri package metadata to the release version for one native build."""

    tauri_dir = installer_dir / "src-tauri"
    files = [
        tauri_dir / "tauri.conf.json",
        installer_dir / "package.json",
        installer_dir / "package-lock.json",
        tauri_dir / "Cargo.toml",
        tauri_dir / "Cargo.lock",
    ]
    snapshots = {path: path.read_bytes() for path in files if path.exists()}
    try:
        _write_json_version_if_present(tauri_dir / "tauri.conf.json", version)
        _write_json_version_if_present(installer_dir / "package.json", version)
        _write_package_lock_version_if_present(installer_dir / "package-lock.json", version)
        _write_cargo_package_version_if_present(tauri_dir / "Cargo.toml", version)
        yield
    finally:
        for path, content in snapshots.items():
            path.write_bytes(content)


def _write_json_version_if_present(path: Path, version: str) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_package_lock_version_if_present(path: Path, version: str) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    root_package = payload.get("packages", {}).get("")
    if isinstance(root_package, dict):
        root_package["version"] = version
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_cargo_package_version_if_present(path: Path, version: str) -> None:
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'(?m)^version = "[^"]+"', f'version = "{version}"', content, count=1)
    if count != 1:
        raise RuntimeError(f"Cargo package version not found in {path}")
    path.write_text(updated, encoding="utf-8")


def _prepare_tauri_resources(out_dir: Path, version: str) -> None:
    """Stage runtime assets bundled into the Windows installer."""

    resources = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "resources"
    _clean_tauri_resources()
    resources.mkdir(parents=True, exist_ok=True)
    (resources / ".gitkeep").touch()

    wheelhouse = out_dir / "wheelhouse"
    wheelhouse_ready = (wheelhouse / "WHEELHOUSE-MANIFEST.json").exists()
    if not wheelhouse_ready:
        raise RuntimeError(
            "Windows tester installer requires a built wheelhouse. "
            "Run this script with --python --wheelhouse before --windows-installer."
        )
    _copytree_clean(wheelhouse, resources / "wheelhouse")

    gstreamer_runtime = out_dir / "gstreamer-runtime"
    gstreamer_runtime_archive = gstreamer_runtime / "gstreamer-runtime-linux-x86_64.tar.gz"
    gstreamer_runtime_checksum = gstreamer_runtime / "gstreamer-runtime-linux-x86_64.tar.gz.sha256"
    gstreamer_runtime_ready = (
        gstreamer_runtime_archive.exists()
        and gstreamer_runtime_archive.stat().st_size > 0
        and gstreamer_runtime_checksum.exists()
        and gstreamer_runtime_checksum.stat().st_size > 0
    )
    if not gstreamer_runtime_ready:
        raise RuntimeError(
            "Windows tester installer requires the bundled CivicCast GStreamer runtime. "
            "Build or copy gstreamer-runtime-linux-x86_64.tar.gz and its .sha256 sidecar into "
            f"{gstreamer_runtime} before --windows-installer."
        )
    _validate_gstreamer_runtime_archive(gstreamer_runtime_archive, gstreamer_runtime_checksum)
    _copytree_clean(gstreamer_runtime, resources / "gstreamer-runtime")

    portal_operator = _build_frontend_dist(
        ROOT / "civiccast" / "apps" / "portal-operator",
        resources / "portal-operator",
    )
    portal_public = _build_frontend_dist(
        ROOT / "civiccast" / "apps" / "portal-public",
        resources / "portal-public",
    )
    runtime_build_id = _runtime_resource_build_id(resources)
    manifest = {
        "schema_version": 2,
        "version": version,
        "runtime_build_id": runtime_build_id,
        "wheelhouse_bundled": True,
        "gstreamer_runtime_bundled": True,
        "portal_operator_bundled": portal_operator,
        "portal_public_bundled": portal_public,
        "windows_runtime": "Windows helper for CivicCast local meeting tools",
        "service_url": "http://127.0.0.1:8000",
        "operator_console_url": "http://127.0.0.1:8000/operator/",
        "resident_portal_url": "http://127.0.0.1:8000/",
    }
    (resources / "bootstrap-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _runtime_resource_build_id(resources: Path) -> str:
    """Hash the exact staged runtime bytes, independent of timestamps."""
    digest = hashlib.sha256()
    for path in sorted(resources.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.name in {".gitkeep", "bootstrap-manifest.json"}:
            continue
        relative = path.relative_to(resources).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _clean_tauri_resources() -> None:
    resources = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "resources"
    if not resources.exists():
        return
    for path in resources.iterdir():
        if path.name in {".gitkeep", "headless-bootstrap.ps1"}:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _build_frontend_dist(app_dir: Path, target: Path) -> bool:
    if not app_dir.exists():
        return False
    _run([*_npm_command(), "run", "build"], cwd=app_dir)
    dist = app_dir / "dist"
    if not dist.exists():
        raise RuntimeError(f"{app_dir.name} build did not produce dist/")
    _copytree_clean(dist, target)
    shutil.rmtree(dist)
    return True


def _copytree_clean(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def build_windows_tester_package(
    out_dir: Path,
    version: str,
    installer: Artifact,
) -> Artifact:
    """Build the single tester download package around the Windows installer."""

    package = out_dir / f"civiccast-{version}-windows-tester-package.zip"
    manifest_path = out_dir / f"civiccast-{version}-windows-tester-package.json"
    wheelhouse_manifest = out_dir / "wheelhouse" / "WHEELHOUSE-MANIFEST.json"
    has_authenticode_evidence = _pe_has_authenticode_evidence(installer.path)
    trust_guidance = (
        "Use only the official CivicCast GitHub release asset and compare the published SHA-256 "
        "against the release's .sidecar.json. The Windows installer contains Authenticode signing "
        "evidence (Azure Trusted Signing); verify that Windows reports publisher Scott Converse. "
        "Windows may still show a SmartScreen prompt until the new certificate earns download "
        "reputation - choose More info, confirm the publisher reads Scott Converse, then Run anyway."
        if has_authenticode_evidence
        else "This installer does not contain Authenticode signing evidence and is not an official "
        "CivicCast GitHub release asset. It may be installed only when the release owner explicitly "
        "authorizes this exact SHA-256 for a controlled clean-machine acceptance run. It is not for "
        "public distribution; run the Windows release signing and verification workflow before any "
        "public release."
    )
    payload = {
        "schema_version": 1,
        "version": version,
        "installer": installer.path.name,
        "installer_sha256": _sha256(installer.path),
        "unsigned_installer": not has_authenticode_evidence,
        "wheelhouse_manifest": (
            wheelhouse_manifest.relative_to(out_dir).as_posix()
            if wheelhouse_manifest.exists()
            else None
        ),
        "operator_path": "Open the installer, choose Set up Windows helper if prompted, approve the Windows security prompt, restart if Windows asks, then continue until the operator console opens.",
        "trust_guidance": trust_guidance,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(installer.path, installer.path.name)
        zf.write(manifest_path, manifest_path.name)
        if wheelhouse_manifest.exists():
            for path in sorted((out_dir / "wheelhouse").rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(out_dir).as_posix())
    return Artifact(package, "windows-tester-package")


def build_clean_windows_proof_kit(
    out_dir: Path,
    version: str,
    installer: Artifact,
) -> Artifact:
    """Build a single transfer kit for the external clean Windows proof host."""

    package = out_dir / f"civiccast-{version}-clean-windows-proof-kit.zip"
    installer_sha256 = _sha256(installer.path)
    readme = _clean_windows_proof_readme(version, installer.path.name, installer_sha256)
    verifier = _clean_windows_proof_verifier(version, installer.path.name, installer_sha256)
    directive = _clean_windows_proof_directive(version, installer.path.name, installer_sha256)
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(installer.path, f"incoming/{installer.path.name}")
        zf.writestr("SHA256SUMS.txt", f"{installer_sha256}  incoming/{installer.path.name}\n")
        zf.writestr("README.md", readme)
        zf.writestr("VERIFY-AND-LAUNCH.ps1", verifier)
        zf.writestr("proof-directive.md", directive)
    return Artifact(package, "clean-windows-proof-kit")


def _clean_windows_proof_readme(version: str, installer_name: str, sha256: str) -> str:
    return f"""# CivicCast v{version} Clean Windows Proof Kit

This ZIP is the complete transfer package for the external clean Windows proof
machine. It includes the installer under test, checksum sidecar, verifier
script, and Codex proof directive.

## Use On The Proof Machine

1. Extract this ZIP to `C:\\CivicCastProof`.
2. Open PowerShell as the normal tester user.
3. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   C:\\CivicCastProof\\VERIFY-AND-LAUNCH.ps1
   ```

4. After the installer opens, give Codex the contents of
   `C:\\CivicCastProof\\proof-directive.md` and let it run the proof.

## Artifact Under Test

- File: `C:\\CivicCastProof\\incoming\\{installer_name}`
- SHA-256: `{sha256}`

Windows 11 reports an NT version beginning with `10.0`; this is normal. Treat
build `22000` or newer as Windows 11, and record the product name/build in the
proof report.
"""


def _clean_windows_proof_verifier(version: str, installer_name: str, sha256: str) -> str:
    return f"""# SPDX-License-Identifier: Apache-2.0
$ErrorActionPreference = "Stop"

$ProofRoot = "C:\\CivicCastProof"
$Installer = Join-Path $ProofRoot "incoming\\{installer_name}"
$ExpectedHash = "{sha256}"
$ReportDir = Join-Path $ProofRoot "reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$isWindows11 = $build -ge 22000
Write-Host "CivicCast v{version} clean Windows proof preflight"
Write-Host ("OS: {{0}} {{1}} build {{2}}" -f $os.Caption, $os.Version, $os.BuildNumber)
Write-Host ("User: {{0}}\\{{1}}" -f $env:USERDOMAIN, $env:USERNAME)

if (-not $isWindows11) {{
  throw "This proof requires Windows 11 build 22000 or newer. Detected $($os.Caption) build $($os.BuildNumber)."
}}

if (-not (Test-Path $Installer)) {{
  throw "Installer is missing: $Installer. Extract the proof kit to C:\\CivicCastProof and retry."
}}

$actual = (Get-FileHash -Algorithm SHA256 -Path $Installer).Hash.ToLowerInvariant()
if ($actual -ne $ExpectedHash) {{
  throw "Installer hash mismatch. Expected $ExpectedHash but got $actual."
}}

$signature = Get-AuthenticodeSignature -FilePath $Installer
if ($signature.Status -ne "Valid") {{
  throw "Installer Authenticode signature is not valid. Detected $($signature.Status)."
}}

$requiredFeatureNames = @(
  "Microsoft-Windows-Subsystem-Linux",
  "VirtualMachinePlatform"
)
$requiredFeatures = [ordered]@{{}}
$requiredFeaturesAbsent = $true
foreach ($name in $requiredFeatureNames) {{
  $feature = Get-CimInstance Win32_OptionalFeature -Filter "Name='$name'" -ErrorAction SilentlyContinue
  $state = if ($null -eq $feature) {{ "missing" }} else {{ [string]$feature.InstallState }}
  $requiredFeatures[$name] = $state
  if ($state -eq "1") {{
    $requiredFeaturesAbsent = $false
  }}
}}

# A clean machine has no WSL: `wsl.exe --list` writes "WSL is not installed" to
# stderr and exits 1. Under `$ErrorActionPreference = "Stop"` that native stderr
# becomes a terminating NativeCommandError (`2>$null` does NOT suppress it),
# which used to crash this proof tool on exactly the clean machines it exists to
# verify. Redirect stderr at the cmd.exe level so PowerShell never sees it, and
# treat any failure as zero distributions.
$wslDistributions = @()
try {{
  $wslRaw = & cmd.exe /c "wsl.exe --list --quiet 2>nul"
  $wslDistributions = @($wslRaw | ForEach-Object {{ $_.Trim([char]0).Trim() }} | Where-Object {{ $_ }})
}} catch {{
  $wslDistributions = @()
}}
$priorPaths = @(
  "$env:LOCALAPPDATA\\CivicCast",
  "$env:LOCALAPPDATA\\CivicCast Installer",
  "$env:LOCALAPPDATA\\Programs\\CivicCast",
  "$env:APPDATA\\CivicCast",
  "$env:PROGRAMDATA\\CivicCast",
  "$env:USERPROFILE\\.civiccast",
  "C:\\CivicCast"
)
$presentPriorPaths = @($priorPaths | Where-Object {{ Test-Path -LiteralPath $_ }})
$priorProcesses = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {{ $_.ProcessName -match '^civiccast' }} | Select-Object -ExpandProperty ProcessName -Unique)
$uninstallRoots = @(
  'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall',
  'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
)
$priorRegistrations = @(
  foreach ($root in $uninstallRoots) {{
    Get-ItemProperty "$root\\*" -ErrorAction SilentlyContinue |
      Where-Object {{ $_.DisplayName -match '^CivicCast' }} |
      Select-Object -ExpandProperty DisplayName
  }}
)
# rc17 F-1: Win32_OptionalFeature reports the *configured* InstallState, which
# goes stale between disabling a feature and the reboot that applies it. A
# machine with a fully working WSL can therefore claim both features are
# absent, and this tool would certify it clean -- letting leftovers quietly
# help an install that was supposed to prove itself from nothing. Corroborate
# with wsl.exe itself: on a genuinely clean machine `wsl.exe --status` exits
# non-zero and prints nothing. Same cmd.exe stderr redirect as above, for the
# same NativeCommandError reason.
$wslStatusWorking = $false
try {{
  $wslStatusRaw = & cmd.exe /c "wsl.exe --status 2>nul"
  $wslStatusLines = @($wslStatusRaw | ForEach-Object {{ $_.Trim([char]0).Trim() }} | Where-Object {{ $_ }})
  if ($LASTEXITCODE -eq 0 -and $wslStatusLines.Count -gt 0) {{
    $wslStatusWorking = $true
  }}
}} catch {{
  $wslStatusWorking = $false
}}
if ($wslStatusWorking) {{
  $requiredFeaturesAbsent = $false
}}

$priorCivicCastDistro = @($wslDistributions | Where-Object {{ $_ -eq "CivicCast-Ubuntu-24.04" }})
$priorCivicCastAbsent = (
  $presentPriorPaths.Count -eq 0 -and
  $priorProcesses.Count -eq 0 -and
  $priorRegistrations.Count -eq 0 -and
  $priorCivicCastDistro.Count -eq 0
)

if (-not $requiredFeaturesAbsent) {{
  throw "Clean-machine preflight failed: WSL or Virtual Machine Platform is already enabled, or wsl.exe still responds (a disabled feature that has not rebooted yet still counts as present)."
}}
if (-not $priorCivicCastAbsent) {{
  throw "Clean-machine preflight failed: prior CivicCast state, registration, process, or WSL distribution is present."
}}

$computer = Get-CimInstance Win32_ComputerSystem

$preflight = [ordered]@{{
  version = "{version}"
  generated_at = (Get-Date).ToString("o")
  os_caption = $os.Caption
  os_version = $os.Version
  os_build = $os.BuildNumber
  is_windows_11 = $isWindows11
  user = "$env:USERDOMAIN\\$env:USERNAME"
  installer = $Installer
  installer_sha256 = $actual
  signature_status = [string]$signature.Status
  signer = [string]$signature.SignerCertificate.Subject
  cpu = [string]$computer.SystemFamily
  ram_bytes = [int64]$computer.TotalPhysicalMemory
  required_features = $requiredFeatures
  required_features_absent = $requiredFeaturesAbsent
  wsl_status_working = $wslStatusWorking
  wsl_distributions = $wslDistributions
  prior_civiccast_paths = $presentPriorPaths
  prior_civiccast_processes = $priorProcesses
  prior_civiccast_registrations = $priorRegistrations
  prior_civiccast_absent = $priorCivicCastAbsent
}}
$preflight | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $ReportDir "preflight.json")

Write-Host "Preflight passed. Launching installer..."
Start-Process -FilePath $Installer
Write-Host "Installer launched. Continue with C:\\CivicCastProof\\proof-directive.md in Codex."
"""


def _clean_windows_proof_directive(version: str, installer_name: str, sha256: str) -> str:
    report_name = f"v{version}-clean-windows-proof.md"
    return f"""# CivicCast v{version} Clean Windows Proof Directive

Use this on a freshly reset Windows proof machine. Do not modify product code,
tag releases, or publish artifacts from the proof machine.

Run this as a collect-and-continue proof. Record recoverable mismatches as
findings and keep moving when an equivalent actual path, label, or screenshot
can be found. Stop immediately only for a blocker that prevents safe
continuation: artifact hash mismatch, installer cannot launch, UAC is canceled
when Windows requires elevation, destructive cleanup risk, missing required
proof artifact with no equivalent file, dashboard cannot be reached after
retry, or a secret exposure that would make further screenshots unsafe.

## Proof Root

- `C:\\CivicCastProof`

The extracted proof kit must contain:

- `C:\\CivicCastProof\\incoming\\{installer_name}`
- `C:\\CivicCastProof\\SHA256SUMS.txt`
- `C:\\CivicCastProof\\VERIFY-AND-LAUNCH.ps1`
- `C:\\CivicCastProof\\proof-directive.md`

Do not copy repo working directories, build folders, or old CivicCast state to
the proof machine.

## Required Preflight

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
C:\\CivicCastProof\\VERIFY-AND-LAUNCH.ps1
```

The verifier must confirm:

- Windows 11 by product/build, treating build 22000+ as Windows 11 even though
  the NT version starts with 10.0
- current user
- installer SHA-256 `{sha256}`
- a valid Authenticode signature and named signer
- artifact under test `C:\\CivicCastProof\\incoming\\{installer_name}`
- both required Windows features are absent before installation
- no prior CivicCast path, process, uninstall registration, or
  `CivicCast-Ubuntu-24.04` distribution is present

Before installing, record:

- OS product name, version, and build
- current user
- hardware summary
- WSL status before install
- no pre-existing CivicCast install/state under Program Files, LOCALAPPDATA,
  `C:\\CivicCast`, or WSL distributions unless created during this proof

## Proof Steps

1. Verify `SHA256SUMS.txt` matches `{installer_name}`.
2. Run the installer as a normal non-developer tester would.
3. Record whether the installer reaches the CivicCast Installer UI.
4. Continue through Windows feature enablement, restart/resume, Ubuntu, local
   runtime, storage, secret generation, and startup. Record the visible phase,
   step count, elapsed time, heartbeat, and restart guidance throughout; a
   static progress view with no changing heartbeat is a failure.
5. If the VM cannot run the Windows helper because nested virtualization is
   unavailable,
   capture the exact installer-visible message, `wsl.exe --status`, and
   `wsl.exe -l -v`, then mark the proof `partial` rather than hiding the
   environment boundary.
6. Complete first-admin setup, save the recovery kit with codes redacted from
   evidence, sign in, and verify storage and upload locations.
7. Prove backup write/read/delete and run the scoped database recovery drill.
   Record the exact scope reported; do not relabel it as a full-station restore.
8. Create or upload short sample media, validate it, and run private packaging.
   Before publication, confirm resident metadata and raw HLS return 404. Apply
   explicit Portal-only approval, then confirm resident metadata and HLS playback
   work through the resident portal. Do not substitute a live-ingest claim.
9. Generate a redacted support bundle and record its path.
10. Run repair/relaunch and confirm setup, admin access, data, and health persist.
11. Run uninstall cleanup and verify the app, processes, uninstall registration,
    product paths, and `CivicCast-Ubuntu-24.04` distribution are gone. Reinstall
    once from the same exact installer, reach the dashboard again, then perform
    final uninstall cleanup and repeat the absence probes.
12. Confirm the report and screenshots do not expose tokens, passwords, private
   keys, provider credentials, recovery codes, or resident data.

## Evidence To Capture

- `C:\\CivicCastProof\\reports\\preflight.json`
- screenshots for installer start, Windows helper/restart/resume if shown,
  dashboard handoff if reached, recovery kit with codes redacted,
  private packaging, pre-publication 404 results, Portal-only approval,
  resident metadata and HLS playback, repair/relaunch, uninstall cleanup,
  reinstall, and support bundle
- support bundle path if generated
- all relevant installer logs or state JSON files

Write the final report to:

`C:\\CivicCastProof\\reports\\{report_name}`

The report must include machine facts, artifact hash, exact pass/fail status for
each step, recoverable findings, screenshot/log paths, support bundle path if
available, operator friction, and final verdict: `passed`, `partial`, or
`failed`.

Pass criteria:

- The installer reaches the operator dashboard without requiring terminal
  commands.
- The Windows helper starts successfully.
- First admin, recovery kit, storage, backup proof, scoped database recovery,
  private packaging, Portal-only approval, resident metadata and HLS playback,
  repair/relaunch, uninstall cleanup, reinstall, final cleanup, and support
  bundle all complete.
- No secret values appear in the report or screenshots.
"""


def build_container_manifest(out_dir: Path, version: str) -> Artifact:
    payload = {
        "image": "ghcr.io/scottconverse/civiccast",
        "tag": version,
        "source": "docker/cleanroom.Dockerfile",
        "build_command": "docker build --file docker/cleanroom.Dockerfile --tag ghcr.io/scottconverse/civiccast:${VERSION} .",
        "attestation": "GitHub artifact attestation is produced by .github/workflows/release-artifacts.yml.",
    }
    target = out_dir / f"civiccast-{version}-container-image-manifest.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Artifact(target, "container-image-manifest")


def build_cross_platform_installer_artifacts(
    out_dir: Path,
    *,
    version: str,
    available_tools: dict[str, bool] | None = None,
) -> dict[str, object]:
    """Build deterministic installer artifact proof entries.

    Native OS package tooling may be unavailable on a developer workstation.
    Those lanes are represented as blocked proof instead of being omitted or
    marked successful.
    """

    tools = available_tools or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []

    # The deb-package and rpm-package lanes are gone with build_deb/build_rpm,
    # along with the _rpm_version_fields helper that generated the .rpm
    # filename. Keeping a proof entry for a package this product no longer
    # builds would have been a manifest that describes an artifact nobody can
    # produce.
    specs = [
        ("macos-pkg", f"civiccast-{version}.pkg", "pkgbuild", "pkg", "launchd"),
        (
            "windows-tauri-installer",
            f"civiccast-{version}-windows-installer.exe",
            "tauri-windows",
            "windows-tauri-exe",
            # Was "wsl2-systemd" -- the Windows installer registers a Windows
            # service through the SCM (civiccast/native/supervisor/service.py),
            # and has since the native lane existed. That value described the
            # superseded WSL2 install path.
            "windows-scm",
        ),
    ]
    for kind, filename, tool, package_kind, manager in specs:
        if tools.get(tool):
            artifact = out_dir / filename
            artifact.write_bytes(f"CivicCast {kind} {version}\n".encode())
            entries.append(
                _installer_artifact_entry(
                    out_dir,
                    artifact,
                    kind=kind,
                    package_kind=package_kind,
                    service_manager=manager,
                )
            )
        else:
            entries.append(
                {
                    "kind": kind,
                    "filename": filename,
                    "status": "blocked",
                    "sha256": "",
                    "sidecar": "",
                    "proof": f"{tool} tooling unavailable; native package proof is blocked.",
                }
            )

    # windows-wsl2-bootstrap-manifest and container-manifest are both gone:
    # the first described installing into WSL2 Ubuntu, the second the Docker
    # image built by the deleted docker/ tree.
    for kind, filename, package_kind, manager in [
        (
            "portable-archive",
            f"civiccast-{version}-portable.tar.gz",
            "portable",
            # A portable archive registers no service at all; "systemd" here
            # was inherited from the Linux lane and was never true of it.
            "none",
        ),
    ]:
        artifact = out_dir / filename
        artifact.write_bytes(f"CivicCast {kind} {version}\n".encode())
        entries.append(
            _installer_artifact_entry(
                out_dir,
                artifact,
                kind=kind,
                package_kind=package_kind,
                service_manager=manager,
            )
        )

    manifest: dict[str, object] = {
        "version": version,
        "artifacts": entries,
        "windows_support": "Windows setup installs CivicCast natively: a signed installer, a Windows service, and a bundled runtime. No WSL, no Docker, no Linux.",
    }
    target = out_dir / f"civiccast-{version}-cross-platform-installers.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _installer_artifact_entry(
    out_dir: Path,
    artifact: Path,
    *,
    kind: str,
    package_kind: str,
    service_manager: str,
) -> dict[str, object]:
    digest = _sha256(artifact)
    sidecar = artifact.with_name(artifact.name + ".sidecar.json")
    sigstore_bundle = artifact.with_name(artifact.name + ".sigstore.json")
    # ponytail: signed/attestation must reflect real bytes on disk, never a
    # literal claim. Linux/macOS artifacts prove signing via a cosign sigstore
    # bundle (written by a separate attest-blob step in release-artifacts.yml);
    # the Windows .exe proves it via an embedded Authenticode signature. Either
    # counts as signed; a plain unsigned build has neither and reads false.
    is_signed = sigstore_bundle.exists() or _pe_has_authenticode_evidence(artifact)
    attestation = (
        sigstore_bundle.relative_to(out_dir).as_posix() if sigstore_bundle.exists() else None
    )
    sidecar_payload = {
        "sha256": digest,
        "attestation": attestation,
        "install_manifest": {
            "signed": is_signed,
            "service": {
                "manager": service_manager,
                "name": "civiccast",
                "host_service": False,
            },
            # Native stations run the egress worker as a child of the
            # Windows supervisor, not as a second registered service.
            "additional_services": [],
            "bootstrap": {"package_kind": package_kind},
        },
    }
    sidecar.write_text(
        json.dumps(sidecar_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "kind": kind,
        "filename": artifact.relative_to(out_dir).as_posix(),
        "status": "ok",
        "sha256": digest,
        "sidecar": sidecar.relative_to(out_dir).as_posix(),
        "proof": "Artifact bytes hashed with sidecar and attestation reference.",
    }


def _artifact_record(
    artifacts: list[Artifact],
    *,
    kind: str,
    out_dir: Path,
    filename: str | None = None,
) -> dict[str, str] | None:
    for artifact in artifacts:
        relative = artifact.path.relative_to(out_dir).as_posix()
        if artifact.kind == kind and (filename is None or relative == filename):
            return {
                "filename": relative,
                "kind": artifact.kind,
            }
    return None


def _beta_handoff_acquisition(out_dir: Path, artifacts: list[Artifact]) -> dict[str, object]:
    wheel = next(
        (
            artifact
            for artifact in artifacts
            if artifact.kind in {"python-wheel", "python-package"}
            and artifact.path.suffix == ".whl"
        ),
        None,
    )
    if wheel is None:
        wheel = next(
            (
                artifact
                for artifact in artifacts
                if artifact.path.parent == out_dir
                and artifact.path.name.startswith("civiccast-")
                and artifact.path.suffix == ".whl"
            ),
            None,
        )
    windows_installer = _artifact_record(
        artifacts,
        kind="windows-tauri-installer",
        out_dir=out_dir,
    )
    wheelhouse = _artifact_record(
        artifacts,
        kind="python-wheelhouse-manifest",
        out_dir=out_dir,
    )
    model_bundle_manifest = _artifact_record(
        artifacts,
        kind="model-bundle-manifest",
        out_dir=out_dir,
    )
    clean_windows_proof_kit = _artifact_record(
        artifacts,
        kind="clean-windows-proof-kit",
        out_dir=out_dir,
    )
    gstreamer_runtime = _artifact_record(
        artifacts,
        kind="release-artifact",
        filename="gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz",
        out_dir=out_dir,
    )
    if wheel is not None:
        wheel_record = {
            "filename": wheel.path.relative_to(out_dir).as_posix(),
            "kind": "python-wheel",
        }
    else:
        wheel_record = None

    wheelhouse_payload: dict[str, object] = {}
    if wheelhouse is not None:
        wheelhouse_path = out_dir / wheelhouse["filename"]
        try:
            loaded = json.loads(wheelhouse_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            wheelhouse_payload = loaded
    install_command = wheelhouse_payload.get("install_command")
    hashes = {
        "windows_installer": _record_hash(out_dir, windows_installer),
        "wheel": _record_hash(out_dir, wheel_record),
        "wheelhouse": _record_hash(out_dir, wheelhouse),
        "model_bundle_manifest": _record_hash(out_dir, model_bundle_manifest),
        "clean_windows_proof_kit": _record_hash(out_dir, clean_windows_proof_kit),
        "gstreamer_runtime": _record_hash(out_dir, gstreamer_runtime),
    }
    return {
        "windows_installer": windows_installer,
        "wheel": wheel_record,
        "wheelhouse": wheelhouse,
        "model_bundle_manifest": model_bundle_manifest,
        "clean_windows_proof_kit": clean_windows_proof_kit,
        "gstreamer_runtime": gstreamer_runtime,
        "hashes": hashes,
        "install_command": install_command
        if isinstance(install_command, str)
        else "python -m pip install --no-index --find-links wheelhouse 'wheelhouse/civiccast-<version>-py3-none-any.whl[captions-runtime]'",
        "windows_runtime": "Windows setup installs CivicCast natively: a signed installer registers a Windows service (SCM) that supervises the control plane, Postgres, NATS and the media workers from a bundled runtime. No WSL, no Docker, no Linux.",
    }


def _record_hash(out_dir: Path, record: dict[str, str] | None) -> str:
    if record is None:
        return ""
    path = out_dir / record["filename"]
    return _sha256(path) if path.exists() else ""


def write_artifact_manifest(out_dir: Path, version: str, artifacts: list[Artifact]) -> Artifact:
    known = {artifact.path.resolve(): artifact for artifact in artifacts}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith("-release-artifacts-manifest.json"):
            continue
        if any(part.startswith("_") for part in path.relative_to(out_dir).parts):
            continue
        known.setdefault(path.resolve(), Artifact(path, "release-artifact"))
    # Published release artifacts are the TOP-LEVEL files in out_dir. Build
    # intermediates that live in a subdirectory -- notably the bundled Linux
    # wheelhouse (wheelhouse/*.whl + WHEELHOUSE-MANIFEST.json) that the installer
    # consumes internally and that is NOT uploaded as a GitHub release asset -- must
    # not appear in the published manifest. Otherwise the publish-manifest merge,
    # which re-hashes every referenced file from each job's uploaded bundle, fails
    # closed on a file that a given per-job bundle doesn't carry (the Windows bundle
    # omits the wheelhouse; the Linux bundle happens to include it). See gate-civiccast.
    out_dir_resolved = out_dir.resolve()
    all_artifacts = list(known.values())
    # Only the top-level published artifacts go in the "artifacts" ledger (the merge
    # re-hashes each entry from a per-job bundle). beta_handoff_acquisition keeps the
    # full set -- it ties the air-gapped handoff bundle (installer + wheel + wheelhouse
    # manifest) and the merge never re-hashes it, so a wheelhouse ref there is safe.
    published = [a for a in all_artifacts if a.path.resolve().parent == out_dir_resolved]
    payload = {
        "version": version,
        "generated_at_unix": int(time.time()),
        "artifacts": [
            {
                "kind": artifact.kind,
                "filename": artifact.path.relative_to(out_dir).as_posix(),
                "sha256": _sha256(artifact.path),
                "size_bytes": artifact.path.stat().st_size,
            }
            for artifact in sorted(published, key=lambda item: item.path.name)
        ],
        "source_state": collect_source_state(repo_root=ROOT),
        "beta_handoff_acquisition": _beta_handoff_acquisition(out_dir, all_artifacts),
    }
    target = out_dir / f"civiccast-{version}-release-artifacts-manifest.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Artifact(target, "release-artifacts-manifest")


def merge_release_manifests(input_dirs: list[Path], out_dir: Path, version: str) -> Artifact:
    """Merge the per-job partial manifests into one complete published ledger.

    The Linux and Windows jobs each build a disjoint set of artifacts and each
    writes its own ``*-release-artifacts-manifest.json`` listing only its own set.
    Whichever gets uploaded last would otherwise be the sole published ledger,
    silently omitting the other job's artifacts (the signed Windows installer,
    its sidecar, tester package, and proof kit never appeared in the published
    manifest). This unions both, re-hashing every referenced file present on disk
    (and trusting the building job's recorded sha for an artifact its CI bundle
    legitimately omits, e.g. the Windows sidecar/attestations). An artifact both
    jobs build — the non-reproducible Python sdist + app wheel — is deduplicated
    to the first, published copy rather than treated as a conflict. A referenced
    artifact that is both absent AND unrecorded is still a hard error.
    """
    merged: dict[str, dict[str, object]] = {}
    source_state: object = None
    beta_handoff: object = None
    generated = 0
    for input_dir in input_dirs:
        manifests = sorted(input_dir.rglob("civiccast-*-release-artifacts-manifest.json"))
        if not manifests:
            raise RuntimeError(f"merge: no release manifest found under {input_dir}")
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        source_state = source_state or manifest.get("source_state")
        if manifest.get("beta_handoff_acquisition"):
            beta_handoff = manifest["beta_handoff_acquisition"]
        generated = max(generated, int(manifest.get("generated_at_unix", 0)))
        for entry in manifest.get("artifacts", []):
            filename = entry["filename"]
            candidate = input_dir / filename
            if not candidate.exists():
                by_name = list(input_dir.rglob(Path(filename).name))
                if by_name:
                    candidate = by_name[0]
            if candidate.exists():
                real_sha = _sha256(candidate)
                real_size = candidate.stat().st_size
                if entry.get("sha256") and entry["sha256"] != real_sha:
                    raise RuntimeError(
                        f"merge: recorded sha for {filename} does not match the file on disk"
                    )
            else:
                # A per-job CI bundle need not carry every artifact its manifest
                # lists (the Windows bundle uploads the installer/tester-package/
                # proof-kit/manifest but not the .sidecar.json or .sigstore.json).
                # The building job already hashed the real bytes, so union on the
                # recorded sha256 rather than failing closed on the missing file. A
                # missing recorded sha256 is still a hard error. See gate-civiccast.
                recorded = entry.get("sha256")
                if not recorded:
                    raise RuntimeError(
                        f"merge: {filename} is absent from the bundle and carries no recorded sha256"
                    )
                real_sha = recorded
                real_size = int(entry.get("size_bytes", 0))
            existing = merged.get(filename)
            if existing is not None:
                # The same filename reported by more than one job is the same logical
                # asset, not a collision: the Python sdist + app wheel are rebuilt
                # non-reproducibly by BOTH the linux and windows jobs (the windows job
                # needs the wheel for the bundled wheelhouse), so their sha differs every
                # run. Only the first-passed job (linux) both records AND uploads its
                # artifacts to the release, so its copy is the published one — keep it and
                # skip the duplicate rather than failing on the expected sha difference.
                # ponytail: first-manifest-wins; input order is linux-then-windows and the
                # linux job uploads everything it lists (`artifacts/release/**`).
                if existing["sha256"] != real_sha:
                    print(
                        f"merge: {filename} was rebuilt with a different sha by a later "
                        f"job; keeping the first (published) copy "
                        f"{str(existing['sha256'])[:12]}",
                        file=sys.stderr,
                    )
                continue
            merged[filename] = {
                "kind": entry.get("kind", "release-artifact"),
                "filename": filename,
                "sha256": real_sha,
                "size_bytes": real_size,
            }
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version,
        "generated_at_unix": generated or int(time.time()),
        "artifacts": sorted(merged.values(), key=lambda item: str(item["filename"])),
        "source_state": source_state,
        "beta_handoff_acquisition": beta_handoff,
    }
    target = out_dir / f"civiccast-{version}-release-artifacts-manifest.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Artifact(target, "release-artifacts-manifest")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--merge-manifests",
        nargs="+",
        type=Path,
        metavar="DIR",
        help=(
            "merge the per-job release manifests found under these directories "
            "into one complete published ledger, then exit (no artifacts built)"
        ),
    )
    parser.add_argument("--python", action="store_true", help="build wheel and sdist")
    parser.add_argument(
        "--wheelhouse",
        action="store_true",
        help="build Linux x64 dependency wheelhouse for air-gapped installs",
    )
    parser.add_argument("--macos-native", action="store_true", help="build .pkg")
    parser.add_argument(
        "--windows-installer",
        action="store_true",
        help="build the Windows Tauri installer executable",
    )
    parser.add_argument(
        "--reuse-installer-exe",
        action="store_true",
        help=(
            "skip the Tauri build and reuse the existing installer .exe already in "
            "out-dir. Used to regenerate the sidecar/tester/proof-kit/manifest AFTER "
            "the .exe has been code-signed, so every checksum describes the signed "
            "binary (see issue #253)."
        ),
    )
    parser.add_argument("--all-portable", action="store_true", help="build non-native artifacts")
    args = parser.parse_args()

    args.out_dir = args.out_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.merge_manifests:
        try:
            merged = merge_release_manifests(
                [d.resolve() for d in args.merge_manifests], args.out_dir, args.version
            )
        except Exception as exc:
            print(f"build_release_artifacts: FAIL - {exc}", file=sys.stderr)
            return 1
        print("build_release_artifacts: PASS")
        print(f"{merged.kind}: {merged.path}")
        return 0

    artifacts: list[Artifact] = []

    try:
        if args.all_portable or not (args.python or args.macos_native):
            artifacts.append(build_source_archive(args.out_dir, args.version))
            artifacts.append(build_model_manifest(args.out_dir, args.version))
            artifacts.append(build_container_manifest(args.out_dir, args.version))
        if args.python:
            artifacts.extend(build_python_artifacts(args.out_dir))
        wheelhouse_built = False
        if args.wheelhouse:
            artifacts.append(build_python_wheelhouse(args.out_dir, args.version))
            wheelhouse_built = True
        if args.macos_native:
            artifacts.append(build_pkg(args.out_dir, args.version))
        if args.windows_installer:
            if not wheelhouse_built:
                artifacts.append(build_python_wheelhouse(args.out_dir, args.version))
            windows_installer = build_windows_tauri_installer(
                args.out_dir, args.version, reuse_existing=args.reuse_installer_exe
            )
            artifacts.append(windows_installer)
            artifacts.append(
                build_windows_tester_package(args.out_dir, args.version, windows_installer)
            )
            artifacts.append(
                build_clean_windows_proof_kit(args.out_dir, args.version, windows_installer)
            )
        artifacts.append(write_artifact_manifest(args.out_dir, args.version, artifacts))
    except Exception as exc:
        print(f"build_release_artifacts: FAIL - {exc}", file=sys.stderr)
        return 1

    print("build_release_artifacts: PASS")
    for artifact in artifacts:
        print(f"{artifact.kind}: {artifact.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
