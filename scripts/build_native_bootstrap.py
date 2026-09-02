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
# The station resources the installer embeds so a DOWNLOAD-ONLY install or
# upgrade of setup.exe alone still carries the signed station index the
# mandatory K1 activation step (nsis-hooks-bootstrap.nsh, d4-activate-station)
# must import. They are produced by the `build-native-station-bundle` CI job
# (scripts/build_native_station_bundle.py) and staged here by
# `.github/workflows/native-beta-candidate-artifacts.yml` before this script
# runs -- this script never fabricates them, it only proves what is there.
STATION_RESOURCE_DIR = SRC_TAURI / "resources" / "station"
STATION_INDEX_RESOURCE = STATION_RESOURCE_DIR / "station-index.json"
STATION_CORE_PACK_RESOURCE = STATION_RESOURCE_DIR / "core.ccpack"
# Deliberately small, and enforced. The whole point of the bootstrap is that
# it carries no station payload; `core`'s payload is a placeholder NOTICE
# (build_native_station_bundle.py::_core_placeholder_sources) and the index is
# a signed JSON envelope. Anything approaching a megabyte here means somebody
# started smuggling real bytes into setup.exe, which is the rule this gate
# exists to keep.
STATION_EMBEDDED_RESOURCE_LIMIT_EXCLUSIVE = 1_000_000
BOOTSTRAP_RESOURCES = {
    "resources/vc_redist.x64.exe": "vc_redist.x64.exe",
    "resources/station/station-index.json": "station/station-index.json",
    "resources/station/core.ccpack": "station/core.ccpack",
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


def validate_embedded_station_resources(
    *,
    index_path: Path = STATION_INDEX_RESOURCE,
    core_pack_path: Path = STATION_CORE_PACK_RESOURCE,
    product_version: str = __version__,
    size_limit_exclusive: int = STATION_EMBEDDED_RESOURCE_LIMIT_EXCLUSIVE,
) -> dict[str, object]:
    """Fail closed unless the two embedded station resources are really there.

    The activation CLI verifies the signed index's ``product_version`` and
    ``compatible_core`` against ``main.rs``'s ``CIVICCAST_VERSION`` (see
    ``run_native_flat_activation_cli``, which passes that constant for both),
    and ``scripts/policy/check_release_identity.py`` already binds that
    constant to ``civiccast._native_version.__version__``. So an index built
    for a different product version would install fine and then fail
    activation on every machine -- exactly the fail-late shape this gate
    turns into a build-time failure.

    Returns the verified manifest identity for the build report.
    """

    for required in (index_path, core_pack_path):
        if not required.is_file():
            raise ValueError(
                "embedded station resource is missing: "
                f"{required}. The station index and core pack are produced by "
                "the build-native-station-bundle job and must be staged under "
                f"{STATION_RESOURCE_DIR} before the Tauri build runs."
            )
        observed = required.stat().st_size
        if observed <= 0:
            raise ValueError(f"embedded station resource is empty: {required}")
        if observed >= size_limit_exclusive:
            raise ValueError(
                "embedded station resource is too large: "
                f"{required} is {observed} bytes, which is not smaller than "
                f"{size_limit_exclusive}; station payload belongs in signed packs"
            )

    envelope = json.loads(index_path.read_text(encoding="utf-8"))
    manifest = envelope.get("manifest") if isinstance(envelope, dict) else None
    if not isinstance(manifest, dict):
        raise ValueError(f"embedded station index is not a signed envelope: {index_path}")
    if not isinstance(envelope.get("signature"), str) or not envelope["signature"]:
        raise ValueError(f"embedded station index carries no signature: {index_path}")
    if manifest.get("kind") != "station-index":
        raise ValueError(f"embedded station index is not a station-index: {manifest.get('kind')!r}")
    for field in ("product_version", "compatible_core"):
        observed_version = manifest.get(field)
        if observed_version != product_version:
            raise ValueError(
                f"embedded station index {field} {observed_version!r} does not match the "
                f"native product version {product_version!r} the activation CLI verifies "
                "against; rebuild the station bundle at this product version"
            )

    packs = manifest.get("packs")
    if not isinstance(packs, list) or not packs:
        raise ValueError(f"embedded station index names no component packs: {index_path}")
    core = next(
        (entry for entry in packs if isinstance(entry, dict) and entry.get("component") == "core"),
        None,
    )
    if core is None:
        raise ValueError(f"embedded station index names no `core` component: {index_path}")
    if core.get("filename") != core_pack_path.name:
        raise ValueError(
            f"embedded station index names core pack {core.get('filename')!r}, but the "
            f"embedded core pack is {core_pack_path.name!r}"
        )
    observed_core_bytes = core_pack_path.stat().st_size
    if core.get("bytes") != observed_core_bytes:
        raise ValueError(
            f"embedded core pack is {observed_core_bytes} bytes, but the signed index "
            f"declares {core.get('bytes')!r}"
        )
    observed_core_sha256 = _sha256(core_pack_path)
    if core.get("sha256") != observed_core_sha256:
        raise ValueError(
            f"embedded core pack SHA-256 {observed_core_sha256} does not match the signed "
            f"index entry {core.get('sha256')!r}"
        )

    return {
        "product_version": manifest["product_version"],
        "compatible_core": manifest["compatible_core"],
        "channel": manifest.get("channel"),
        "signing_key_id": manifest.get("signing_key_id"),
        "index_sha256": _sha256(index_path),
        "index_bytes": index_path.stat().st_size,
        "core_pack_sha256": observed_core_sha256,
        "core_pack_bytes": observed_core_bytes,
        "component_count": len(packs),
    }


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
        # Same reproducibility normalization the redistributable already gets:
        # these two files are staged by CI (not by this script), so their
        # mtimes carry the runner's clock into the NSIS archive unless pinned.
        for station_resource in (STATION_INDEX_RESOURCE, STATION_CORE_PACK_RESOURCE):
            os.utime(station_resource, (SOURCE_DATE_EPOCH, SOURCE_DATE_EPOCH))
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


def build_report(
    setup: Path,
    *,
    key_id: str,
    embedded_station: dict[str, object] | None = None,
) -> dict[str, object]:
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
        "embedded_station": embedded_station,
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
        embedded_station = validate_embedded_station_resources()
        _build(
            args.pack_public_key_base64,
            args.pack_signing_key_id,
            args.vc_redist_x64,
        )
        report = build_report(
            SETUP_ARTIFACT,
            key_id=args.pack_signing_key_id,
            embedded_station=embedded_station,
        )
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
