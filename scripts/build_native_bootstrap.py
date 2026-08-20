#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build and size-gate the small signed-pack CivicCast native bootstrap."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

from civiccast._native_version import __version__

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "civiccast" / "apps" / "installer"
SRC_TAURI = INSTALLER_DIR / "src-tauri"
NATIVE_CONFIG = SRC_TAURI / "tauri.native.conf.json"
VC_REDIST_RESOURCE = SRC_TAURI / "resources" / "vc_redist.x64.exe"
VC_REDIST_EXPECTED_BYTES = 25_635_768
VC_REDIST_EXPECTED_SHA256 = "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b"
BOOTSTRAP_RESOURCES = {
    "resources/vc_redist.x64.exe": "vc_redist.x64.exe",
}
# Tauri names the generated NSIS installer "<productName>_<version>_x64-setup.exe"
# from the EFFECTIVE merged native config. productName ("CivicCast (Native)") is
# stable across releases and stays a literal here; the version segment is NOT --
# chain J (2026-08-02) found this was a hardcoded "1.0.0-rc15" that would have
# silently gone stale (and made this script unable to find its own build output)
# on every future version bump. Sourced from civiccast._native_version, the
# same place tauri.native.conf.json's own "version" field is required to match
# (scripts/policy/check_release_identity.py) -- deliberately NOT
# civiccast._version, which is the separate WSL product line's own identity.
SETUP_ARTIFACT = (
    SRC_TAURI
    / "target"
    / "release"
    / "bundle"
    / "nsis"
    / f"CivicCast (Native)_{__version__}_x64-setup.exe"
)
MAIN_BINARY = SRC_TAURI / "target" / "release" / "CivicCast Native.exe"
GENERATED_NSIS_DIR = SRC_TAURI / "target" / "release" / "nsis" / "x64"
GENERATED_NSIS_SCRIPT = GENERATED_NSIS_DIR / "installer.nsi"
GENERATED_NSIS_OUTPUT = GENERATED_NSIS_DIR / "nsis-output.exe"
BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE = 300_000_000
SOURCE_DATE_EPOCH = 1_704_067_200
TAURI_UNKNOWN_BUNDLE_MARKER = b"__TAURI_BUNDLE_TYPE_VAR_UNK"
TAURI_NSIS_BUNDLE_MARKER = b"__TAURI_BUNDLE_TYPE_VAR_NSS"


def enforce_bootstrap_size(
    observed_bytes: int,
    *,
    limit_exclusive: int = BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE,
) -> int:
    """Return headroom or fail when the bootstrap reaches the strict limit."""

    if observed_bytes <= 0:
        raise ValueError("bootstrap byte length must be positive")
    if observed_bytes >= limit_exclusive:
        raise ValueError(
            "native bootstrap size gate failed: "
            f"{observed_bytes} bytes is not smaller than {limit_exclusive}"
        )
    return limit_exclusive - observed_bytes


def validate_pack_public_key(encoded: str) -> bytes:
    """Require one raw Ed25519 public key for the compiled trust root."""

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("pack public key must be canonical base64") from exc
    if len(decoded) != 32:
        raise ValueError("pack public key must decode to exactly 32 Ed25519 bytes")
    return decoded


def validate_native_bootstrap_config(path: Path = NATIVE_CONFIG) -> None:
    """Prove the native overlay embeds no multi-gigabyte station payload."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("resources") != BOOTSTRAP_RESOURCES:
        raise ValueError(
            "native bootstrap resources must contain only the pinned VC++ "
            "runtime prerequisite; station bytes belong in signed packs"
        )
    windows = bundle.get("windows")
    nsis = windows.get("nsis") if isinstance(windows, dict) else None
    if not isinstance(nsis, dict) or nsis.get("installerHooks") != ("nsis-hooks-bootstrap.nsh"):
        raise ValueError("native bootstrap must use the pack-only NSIS hooks")
    webview = windows.get("webviewInstallMode") if isinstance(windows, dict) else None
    if not isinstance(webview, dict) or webview != {
        "type": "offlineInstaller",
        "silent": True,
    }:
        raise ValueError(
            "native bootstrap must embed the silent offline WebView2 installer; "
            "air-gapped setup must not depend on a download"
        )


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    if not key_id.strip():
        raise ValueError("pack signing key id must not be empty")
    if key_id.startswith("development-") and not allow_development_key:
        raise ValueError(
            "development trust roots require --allow-development-key; "
            "release builds require Scott-approved production key custody"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_vc_redist(
    path: Path,
    *,
    expected_bytes: int = VC_REDIST_EXPECTED_BYTES,
    expected_sha256: str = VC_REDIST_EXPECTED_SHA256,
) -> Path:
    """Require the reviewed Microsoft x64 runtime prerequisite exactly."""

    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"VC++ redistributable is not a regular file: {resolved}")
    observed_bytes = resolved.stat().st_size
    if observed_bytes != expected_bytes:
        raise ValueError(
            "VC++ redistributable byte length mismatch: "
            f"expected {expected_bytes}, observed {observed_bytes}"
        )
    observed_sha256 = _sha256(resolved)
    if observed_sha256 != expected_sha256:
        raise ValueError(
            "VC++ redistributable SHA-256 mismatch: "
            f"expected {expected_sha256}, observed {observed_sha256}"
        )
    return resolved


def _run(
    command: list[str],
    *,
    cwd: Path = INSTALLER_DIR,
    env: dict[str, str] | None = None,
) -> None:
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        rendered = subprocess.list2cmdline(command)
        raise RuntimeError(
            f"native bootstrap build command failed ({completed.returncode}): {rendered}"
        )


def reproducible_build_environment(base: dict[str, str]) -> dict[str, str]:
    """Return a controlled Rust/PE build environment for repeatable bytes."""

    env = base.copy()
    remapped_source = "C:/civiccast-src"
    remapped_cargo = "C:/cargo-home"
    rust_flags = [
        "-C",
        "link-arg=/Brepro",
        f"--remap-path-prefix={ROOT}={remapped_source}",
        f"--remap-path-prefix={Path.home() / '.cargo'}={remapped_cargo}",
    ]
    env.pop("RUSTFLAGS", None)
    env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(rust_flags)
    env["SOURCE_DATE_EPOCH"] = str(SOURCE_DATE_EPOCH)
    return env


def patch_tauri_bundle_type(binary: bytes) -> bytes:
    """Patch Tauri's fixed marker to the NSIS bundle type exactly once."""

    occurrences = binary.count(TAURI_UNKNOWN_BUNDLE_MARKER)
    if occurrences != 1:
        raise ValueError(
            "Tauri bundle marker contract failed: expected exactly one "
            f"{TAURI_UNKNOWN_BUNDLE_MARKER!r}, found {occurrences}"
        )
    return binary.replace(
        TAURI_UNKNOWN_BUNDLE_MARKER,
        TAURI_NSIS_BUNDLE_MARKER,
        1,
    )


def _find_makensis() -> Path:
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        nsis = Path(local_app_data) / "tauri" / "NSIS"
        candidates.extend((nsis / "makensis.exe", nsis / "Bin" / "makensis.exe"))
    discovered = shutil.which("makensis")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("makensis was not found after Tauri's NSIS build completed")


def normalize_nsis_bootstrap() -> None:
    """Repack NSIS with deterministic app bytes and source-file timestamp."""

    for required in (MAIN_BINARY, GENERATED_NSIS_SCRIPT):
        if not required.is_file():
            raise FileNotFoundError(f"generated native bootstrap input is missing: {required}")

    original = MAIN_BINARY.read_bytes()
    patched = patch_tauri_bundle_type(original)
    original_stat = MAIN_BINARY.stat()
    temporary_setup = SETUP_ARTIFACT.with_suffix(".normalized.tmp")
    if temporary_setup.exists():
        temporary_setup.unlink()

    try:
        MAIN_BINARY.write_bytes(patched)
        os.utime(MAIN_BINARY, (SOURCE_DATE_EPOCH, SOURCE_DATE_EPOCH))
        if GENERATED_NSIS_OUTPUT.exists():
            GENERATED_NSIS_OUTPUT.unlink()
        _run(
            [str(_find_makensis()), "/V2", str(GENERATED_NSIS_SCRIPT)],
            cwd=GENERATED_NSIS_DIR,
        )
        if not GENERATED_NSIS_OUTPUT.is_file():
            raise FileNotFoundError(f"normalized NSIS output is missing: {GENERATED_NSIS_OUTPUT}")
        temporary_setup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(GENERATED_NSIS_OUTPUT, temporary_setup)
        temporary_setup.replace(SETUP_ARTIFACT)
    finally:
        MAIN_BINARY.write_bytes(original)
        os.utime(
            MAIN_BINARY,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        if temporary_setup.exists():
            temporary_setup.unlink()


def _build(public_key: str, key_id: str, vc_redist: Path) -> None:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    tauri = INSTALLER_DIR / "node_modules" / ".bin" / ("tauri.cmd" if os.name == "nt" else "tauri")
    reviewed_redist = validate_vc_redist(vc_redist)
    VC_REDIST_RESOURCE.parent.mkdir(parents=True, exist_ok=True)
    if VC_REDIST_RESOURCE.exists():
        VC_REDIST_RESOURCE.unlink()
    try:
        shutil.copyfile(reviewed_redist, VC_REDIST_RESOURCE)
        os.utime(VC_REDIST_RESOURCE, (SOURCE_DATE_EPOCH, SOURCE_DATE_EPOCH))
        _run([npm, "ci"])
        if not tauri.is_file():
            raise RuntimeError("Tauri CLI was not installed by npm ci")
        env = reproducible_build_environment(os.environ.copy())
        env["CIVICCAST_PACK_PUBLIC_KEY_BASE64"] = public_key
        env["CIVICCAST_PACK_SIGNING_KEY_ID"] = key_id
        if key_id.startswith("development-"):
            env["CIVICCAST_ALLOW_DEVELOPMENT_PACK_KEY"] = "1"
        else:
            env.pop("CIVICCAST_ALLOW_DEVELOPMENT_PACK_KEY", None)
        _run(
            [
                str(tauri),
                "build",
                "--config",
                "src-tauri/tauri.native.conf.json",
                "--features",
                "native-packs",
                "--bundles",
                "nsis",
                "--no-sign",
                "--ci",
            ],
            env=env,
        )
        normalize_nsis_bootstrap()
    finally:
        VC_REDIST_RESOURCE.unlink(missing_ok=True)


def build_report(setup: Path, *, key_id: str) -> dict[str, object]:
    """Measure an already-built unsigned bootstrap and enforce the size gate."""

    if not setup.is_file():
        raise FileNotFoundError(f"native bootstrap artifact is missing: {setup}")
    observed_bytes = setup.stat().st_size
    headroom = enforce_bootstrap_size(observed_bytes)
    return {
        "artifact": str(setup.resolve()),
        "bytes": observed_bytes,
        "limit_exclusive": BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE,
        "headroom_bytes": headroom,
        "pack_signing_key_id": key_id,
        "sha256": _sha256(setup),
        "signed": False,
        "status": "PASS",
    }


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"build_native_bootstrap: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-public-key-base64", required=True)
    parser.add_argument("--pack-signing-key-id", required=True)
    parser.add_argument("--vc-redist-x64", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--allow-development-key", action="store_true")
    args = parser.parse_args()
    try:
        validate_pack_public_key(args.pack_public_key_base64)
        require_allowed_signing_key(
            args.pack_signing_key_id,
            allow_development_key=args.allow_development_key,
        )
        validate_native_bootstrap_config()
        _build(
            args.pack_public_key_base64,
            args.pack_signing_key_id,
            args.vc_redist_x64,
        )
        report = build_report(SETUP_ARTIFACT, key_id=args.pack_signing_key_id)
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"bootstrap report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(report, indent=2) + "\n"
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
        print(rendered, end="")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        _fail(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
