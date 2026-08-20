#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Build the signed product-owned ``native-ollama-runtime`` Windows pack.

The first-run acquisition flow downloads model manifests and blobs, but it
does not deliver ``ollama.exe``. This builder packages the complete reviewed
Windows runtime archive, without model bytes, so bootstrap staging can place it
at ``<INSTDIR>\dependencies\ollama`` before the supervisor starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast._native_version import __version__  # noqa: E402
from civiccast.installer.native_packs import build_native_pack  # noqa: E402
from scripts.build_native_caption_pack import require_allowed_signing_key  # noqa: E402
from scripts.provision_native_runtime_dependencies import (  # noqa: E402
    LOCK_PATH,
    fetch_locked_artifact,
    load_lock,
    safe_extract_zip,
)

OLLAMA_RUNTIME_COMPONENT: Final[str] = "native-ollama-runtime"
OLLAMA_VERSION: Final[str] = "0.30.6"
OLLAMA_SPDX_LICENSE: Final[str] = "MIT"
OLLAMA_EXECUTABLES: Final[tuple[str, ...]] = ("ollama.exe",)
_REPARSE_POINT: Final[int] = 0x400


class OllamaPackBuildError(RuntimeError):
    """The native Ollama runtime pack could not be built."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_file(path: Path, *, label: str) -> Path:
    try:
        details = path.lstat()
    except OSError as exc:
        raise OllamaPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise OllamaPackBuildError(f"{label} must be a regular non-reparse file: {path}")
    return path


def _require_real_directory(path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        details = path.lstat()
    except OSError as exc:
        raise OllamaPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISDIR(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise OllamaPackBuildError(f"{label} must be a real directory: {path}")
    return path


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    _require_regular_file(path, label="pack signing private key")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise OllamaPackBuildError("pack signing private key must be Ed25519")
    return key


def acquire_ollama_pack_sources(cache: Path, *, lock_path: Path = LOCK_PATH) -> tuple[Path, Path]:
    """Acquire only the reviewed Ollama archive and its separately pinned license."""

    lock = load_lock(lock_path)
    artifact = lock["artifacts"]["ollama"]
    if str(artifact["version"]) != OLLAMA_VERSION:
        raise OllamaPackBuildError(
            "ollama artifact version drifted from this builder's reviewed pin: "
            f"lock has {artifact['version']!r}, builder expects {OLLAMA_VERSION!r}"
        )
    if str(artifact["spdx_license"]) != OLLAMA_SPDX_LICENSE:
        raise OllamaPackBuildError(
            "ollama artifact license drifted from this builder's reviewed pin: "
            f"lock has {artifact['spdx_license']!r}, builder expects {OLLAMA_SPDX_LICENSE!r}"
        )
    expected_executables = tuple(str(item) for item in artifact["expected_executables"])
    if expected_executables != OLLAMA_EXECUTABLES:
        raise OllamaPackBuildError(
            "ollama artifact expected_executables drifted from this builder's reviewed pin: "
            f"lock has {expected_executables!r}, builder expects {OLLAMA_EXECUTABLES!r}"
        )
    notice = artifact.get("license_notice")
    if not isinstance(notice, dict):
        raise OllamaPackBuildError("ollama artifact is missing its pinned license notice")

    try:
        archive = fetch_locked_artifact("ollama", artifact, cache / "archives", offline=False)
        license_path = fetch_locked_artifact(
            "ollama-license", notice, cache / "archives", offline=False
        )
        destination = cache / "extracted" / "ollama"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="ollama-fresh-", dir=destination.parent
        ) as temporary:
            fresh = Path(temporary) / "runtime"
            safe_extract_zip(
                archive,
                fresh,
                strip_prefix=str(artifact["strip_prefix"]),
                include=artifact.get("include"),
            )
            _runtime_sources(fresh)
            had_previous = destination.exists() or destination.is_symlink()
            backup_holder: Path | None = None
            previous: Path | None = None
            if had_previous:
                backup_holder = Path(
                    tempfile.mkdtemp(prefix=".ollama-previous-", dir=destination.parent)
                )
                previous = backup_holder / "previous"
                try:
                    destination.replace(previous)
                except OSError:
                    backup_holder.rmdir()
                    raise
            try:
                fresh.replace(destination)
            except OSError as promotion_error:
                if previous is not None:
                    try:
                        previous.replace(destination)
                    except OSError as rollback_error:
                        raise OllamaPackBuildError(
                            "Ollama cache promotion and rollback failed; the previous "
                            f"cache is preserved at {previous}: {rollback_error}"
                        ) from promotion_error
                if backup_holder is not None:
                    backup_holder.rmdir()
                raise
            if backup_holder is not None:
                shutil.rmtree(backup_holder)
    except Exception as exc:
        raise OllamaPackBuildError(f"could not acquire reviewed Ollama runtime: {exc}") from exc
    _require_regular_file(destination / "ollama.exe", label="reviewed Ollama executable")
    return destination, license_path


def _runtime_sources(ollama_root: Path) -> dict[str, Path]:
    root = _require_real_directory(ollama_root, label="Ollama runtime root")
    _require_regular_file(root / "ollama.exe", label="Ollama runtime executable ollama.exe")
    model_root = root / "models"
    if model_root.exists():
        raise OllamaPackBuildError(
            f"Ollama runtime source contains a model store; model bytes belong to acquisition: {model_root}"
        )

    sources: dict[str, Path] = {}
    folded_paths: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        details = candidate.lstat()
        attributes = int(getattr(details, "st_file_attributes", 0))
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            raise OllamaPackBuildError(
                f"Ollama runtime contains a link or reparse point: {candidate}"
            )
        if candidate.is_dir():
            continue
        if not stat.S_ISREG(details.st_mode):
            raise OllamaPackBuildError(f"Ollama runtime contains a non-regular file: {candidate}")
        relative = PurePosixPath(candidate.relative_to(root).as_posix())
        folded = relative.as_posix().casefold()
        if folded in folded_paths:
            raise OllamaPackBuildError(
                f"Ollama runtime contains a case-insensitive path collision: {relative}"
            )
        folded_paths.add(folded)
        sources[relative.as_posix()] = candidate.resolve(strict=True)
    return sources


def _render_notice(runtime_paths: tuple[str, ...]) -> str:
    return (
        "CivicCast native Ollama runtime pack\n\n"
        f"Ollama version: {OLLAMA_VERSION}\n"
        f"Reviewed top-level license: {OLLAMA_SPDX_LICENSE}\n"
        "The pinned upstream license text is included at licenses/ollama/LICENSE.txt.\n"
        "The complete upstream Windows runtime archive is retained because Ollama selects\n"
        "hardware-specific runner libraries at runtime. Model manifests and blobs are not\n"
        "part of this pack; the installer acquires and verifies them separately.\n\n"
        f"Runtime files packed: {len(runtime_paths)}\n"
    )


def build_ollama_pack(
    *,
    output: Path,
    ollama_root: Path,
    license_path: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    compatible_core: str | None = None,
) -> dict[str, object]:
    sources = _runtime_sources(ollama_root)
    license_path = _require_regular_file(license_path, label="pinned Ollama license")
    license_text = license_path.read_text(encoding="utf-8")
    if "MIT License" not in license_text:
        raise OllamaPackBuildError("pinned Ollama license does not contain the MIT License text")
    runtime_paths = tuple(sorted(sources))

    with tempfile.TemporaryDirectory(prefix="civiccast-ollama-pack-") as temporary:
        notice_path = Path(temporary) / "NOTICE.txt"
        notice_path.write_text(_render_notice(runtime_paths), encoding="utf-8", newline="\n")
        sources["licenses/ollama/LICENSE.txt"] = license_path
        sources["notices/ollama-runtime.txt"] = notice_path
        result = build_native_pack(
            output=output,
            component=OLLAMA_RUNTIME_COMPONENT,
            product_version=product_version,
            compatible_core=compatible_core or product_version,
            sources=sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={
                "ollama_version": OLLAMA_VERSION,
                "ollama_spdx_license": OLLAMA_SPDX_LICENSE,
                "ollama_executables": list(OLLAMA_EXECUTABLES),
            },
        )
    return {
        "component": result.component,
        "file_count": result.file_count,
        "output": str(result.path),
        "pack_bytes": result.path.stat().st_size,
        "pack_sha256": result.sha256,
        "payload_bytes": result.total_bytes,
        "payload_tree_sha256": result.payload_tree_sha256,
        "product_version": result.product_version,
        "signing_key_id": result.signing_key_id,
    }


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def prove_ollama_runtime(ollama_root: Path) -> dict[str, object]:
    """Start the exact staged runtime offline and require its version API."""

    executable = _require_regular_file(
        _require_real_directory(ollama_root, label="Ollama runtime root") / "ollama.exe",
        label="Ollama runtime executable ollama.exe",
    )
    port = _free_loopback_port()
    with tempfile.TemporaryDirectory(prefix="civiccast-ollama-proof-") as temporary:
        proof_root = Path(temporary)
        log_path = proof_root / "ollama.log"
        env = {
            **os.environ,
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "OLLAMA_MODELS": str(proof_root / "models"),
            "OLLAMA_NO_CLOUD": "1",
        }
        with log_path.open("w+b") as log:
            process = subprocess.Popen(
                [str(executable), "serve"],
                cwd=executable.parent,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            observed: dict[str, Any] | None = None
            try:
                deadline = time.monotonic() + 45.0
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/version", timeout=2
                        ) as response:
                            observed = json.loads(response.read().decode("utf-8"))
                            break
                    except (OSError, urllib.error.URLError, json.JSONDecodeError):
                        time.sleep(0.25)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        if observed is None:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise OllamaPackBuildError(
                "Ollama runtime proof did not expose /api/version within 45 seconds; "
                f"exit={process.returncode}, log_tail={log_text!r}"
            )
        version = str(observed.get("version", ""))
        if version != OLLAMA_VERSION:
            raise OllamaPackBuildError(
                f"Ollama runtime API version {version!r} != reviewed {OLLAMA_VERSION!r}"
            )
        return {"version": version, "loopback_only": True, "cloud_disabled": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "civiccast-native-ollama-pack-cache",
    )
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--ollama-root", type=Path)
    parser.add_argument("--license", type=Path)
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--product-version", default=__version__)
    parser.add_argument("--compatible-core", default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-development-key", action="store_true")
    parser.add_argument("--skip-runtime-proof", action="store_true")
    args = parser.parse_args()

    try:
        require_allowed_signing_key(
            args.signing_key_id, allow_development_key=args.allow_development_key
        )
        key = load_ed25519_private_key(args.signing_private_key)
        if args.acquire:
            if args.ollama_root or args.license:
                raise OllamaPackBuildError(
                    "--acquire is mutually exclusive with --ollama-root/--license"
                )
            ollama_root, license_path = acquire_ollama_pack_sources(args.cache, lock_path=args.lock)
        elif args.ollama_root is None or args.license is None:
            raise OllamaPackBuildError("pass --acquire or both --ollama-root and --license")
        else:
            ollama_root, license_path = args.ollama_root, args.license

        proof: dict[str, object] = {}
        if not args.skip_runtime_proof:
            proof = prove_ollama_runtime(ollama_root)
        report = build_ollama_pack(
            output=args.output.resolve(),
            ollama_root=ollama_root,
            license_path=license_path,
            signing_private_key=key,
            signing_key_id=args.signing_key_id,
            product_version=args.product_version,
            compatible_core=args.compatible_core,
        )
        report["runtime_proof"] = proof
    except OllamaPackBuildError as exc:
        print(f"build_native_ollama_pack: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"Ollama pack report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
