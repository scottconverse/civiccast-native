#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the signed native ``native-app-payload`` component pack (CPython
3.12 embeddable interpreter + the ``civiccast`` wheel + hash-pinned
third-party dependency wheels) that ``native_pack_staging::
ensure_pack_extracted`` lands at ``$INSTDIR\\runtime\\`` -- closing the gap
where ``$INSTDIR\\runtime\\python.exe`` never existed on a fresh bootstrap
install, so D4 provisioning and D4 service registration
(``native_service_registration.rs``'s ``provision_command`` /
``service_registration_command``, both of which hard-code
``install_root.join("runtime").join("python.exe")``) failed loud on every
real install.

``scripts/build_native_app_payload.py`` (WP-6) already builds the payload
TREE (interpreter + civiccast + deps, deny-by-default license gate, its own
``app-payload-manifest.json`` / ``SHA256SUMS`` / ``LICENSE-BOM.md``). This
script is the missing sibling of ``scripts/build_native_server_pack.py``
(WP2 Core pack) for that tree: it packages an ALREADY-BUILT (or freshly
built) payload tree as a signed ZIP64 ``.ccpack`` via
``civiccast.installer.native_packs.build_native_pack`` -- same
signing-key-id guard, same per-file inventory, same trust wire every other
native component pack uses.

License/provenance is NOT re-derived here. The payload's own build
(``scripts/build_native_app_payload.py``) already ran the deny-by-default
gate (``civiccast.native.app_payload.assert_authorized_app_distributions`` /
``assert_no_prohibited_declared_licenses``) once, at build time. This
builder instead RE-CHECKS that already-proven result by running the
independent post-build verifier
(``scripts.verify_native_app_payload.check_app_payload_verification``) over
the payload tree before packing it -- reusing the WP-6 proof, not repeating
distribution/METADATA analysis a second time. A tree that fails that
independent check (byte drift from its own manifest, an unauthorized
distribution, a GPL/AGPL-recorded license, a missing interpreter file, or
embedded caption-model bytes that belong in the SEPARATE captions-large-v3
pack instead -- ``plan-sub-300mb-bootstrap.md``'s pack split) refuses the
build rather than sign a tree this repo cannot vouch for.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path, PurePosixPath
from shutil import copy2, rmtree
from tempfile import mkdtemp
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast._native_version import __version__  # noqa: E402
from civiccast.installer.native_packs import build_native_pack  # noqa: E402
from civiccast.native.app_payload import (  # noqa: E402
    APP_PAYLOAD_COMPONENT,
    APP_REQUIREMENTS_SHA256,
    INTERPRETER_VERSION,
)
from scripts import build_native_app_payload  # noqa: E402
from scripts import verify_native_runtime_closure as closure_verifier  # noqa: E402
from scripts.verify_native_app_payload import check_app_payload_verification  # noqa: E402

_REPARSE_POINT: Final[int] = 0x400


class AppPayloadPackBuildError(RuntimeError):
    """The native-app-payload pack could not be built."""


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    """Keep development trust roots out of an accidental release build
    (same contract as ``build_native_server_pack``/``build_native_caption_pack``)."""

    if key_id.startswith("development-") and not allow_development_key:
        raise AppPayloadPackBuildError(
            "development pack signing keys require --allow-development-key; "
            "release packaging must use Scott-approved production key custody"
        )


def require_source_sha(source_sha: object) -> str:
    """Require the exact lowercase full Git SHA signed into this pack."""

    if not (
        isinstance(source_sha, str)
        and len(source_sha) == 40
        and all(character in "0123456789abcdef" for character in source_sha)
    ):
        raise AppPayloadPackBuildError(
            "source SHA must be exactly 40 lowercase hexadecimal characters"
        )
    return source_sha


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        raise AppPayloadPackBuildError(f"pack signing private key is missing: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise AppPayloadPackBuildError("pack signing private key must be Ed25519")
    return key


def _require_real_directory(path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        details = path.lstat()
    except OSError as exc:
        raise AppPayloadPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISDIR(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise AppPayloadPackBuildError(
            f"{label} must be a real directory, not a link or reparse point: {path}"
        )
    return path


def _collect_payload_sources(payload_root: Path) -> dict[str, Path]:
    """Every regular file under ``payload_root`` -> its pack-relative path
    (identical to its payload-root-relative path, so the extracted tree at
    ``$INSTDIR\\runtime`` is byte-identical to the tree this script packed).
    Refuses symlinks/reparse points/non-regular files, mirroring
    ``build_native_server_pack._collect_data_tree``'s posture."""

    sources: dict[str, Path] = {}
    for candidate in sorted(payload_root.rglob("*")):
        if candidate.is_dir():
            continue
        details = candidate.lstat()
        attributes = int(getattr(details, "st_file_attributes", 0))
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            raise AppPayloadPackBuildError(
                f"app payload tree contains a link or reparse point: {candidate}"
            )
        if not stat.S_ISREG(details.st_mode):
            raise AppPayloadPackBuildError(
                f"app payload tree contains a non-regular file: {candidate}"
            )
        relative = PurePosixPath(candidate.relative_to(payload_root).as_posix())
        sources[relative.as_posix()] = candidate
    if not sources:
        raise AppPayloadPackBuildError(f"app payload tree is empty: {payload_root}")
    return sources


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_closure_metadata(closure_root: Path) -> tuple[dict[str, Path], dict[str, object]]:
    """Verify an independently-built closure before it may enter the app pack."""

    closure_root = _require_real_directory(closure_root, label="GStreamer closure")
    if closure_verifier.main(["--tree", str(closure_root)]) != 0:
        raise AppPayloadPackBuildError("GStreamer closure verification failed")
    manifest_path = closure_root / "runtime-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = str(manifest["gstreamer_version"])
        lock_sha256 = str(manifest["lock_sha256"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AppPayloadPackBuildError(
            f"GStreamer closure manifest is missing or malformed: {manifest_path}"
        ) from exc
    if len(lock_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in lock_sha256
    ):
        raise AppPayloadPackBuildError("GStreamer closure runtime lock SHA-256 is invalid")
    sources = _collect_payload_sources(closure_root)
    entries = [
        {"path": path, "sha256": _sha256(source)} for path, source in sorted(sources.items())
    ]
    from civiccast.installer.native_packs import payload_tree_sha256

    return sources, {
        "gstreamer_version": version,
        "runtime_lock_sha256": lock_sha256,
        "closure_manifest_sha256": _sha256(manifest_path),
        "closure_payload_tree_sha256": payload_tree_sha256(entries),
        "closure_file_count": len(sources),
        "closure_payload_bytes": sum(source.stat().st_size for source in sources.values()),
    }


def _compose_payload_with_closure(payload_root: Path, closure_root: Path) -> Path:
    """Create a fresh pack tree; source payload and closure are never mutated."""

    composed = Path(mkdtemp(prefix="civiccast-native-app-payload-composed-"))
    for relative, source in _collect_payload_sources(payload_root).items():
        destination = composed / PurePosixPath(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, destination)
    closure_destination = composed / "dependencies" / "gstreamer"
    for relative, source in _collect_payload_sources(closure_root).items():
        destination = closure_destination / PurePosixPath(relative)
        try:
            destination.resolve().relative_to(composed.resolve())
        except ValueError as exc:
            raise AppPayloadPackBuildError(
                "GStreamer closure copy resolves outside app payload"
            ) from exc
        if destination.exists():
            raise AppPayloadPackBuildError(
                f"GStreamer closure overlaps the app payload at {destination.relative_to(composed)}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, destination)
    return composed


def build_app_payload_pack(
    *,
    output: Path,
    payload_root: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    source_sha: str,
    gstreamer_closure: Path | None = None,
    compatible_core: str | None = None,
    advisory_pyav_wheel_hash: bool = False,
) -> dict[str, object]:
    """Independently re-verify the built payload tree, then package it as
    the signed ``native-app-payload`` pack.

    The returned report's ``payload_tree_sha256`` (from
    ``civiccast.installer.native_packs.payload_tree_sha256``, computed from
    the SAME signed manifest ``files`` entries ``build_native_pack`` already
    produces -- reused, not re-hashed) lets two machines that each built
    this pack from the same commit compare their PAYLOAD bytes decisively,
    even though their ``pack_sha256``/signing key id necessarily differ
    (each machine signs with its own local development key). Equal
    ``payload_tree_sha256`` across machines is the actual reproducible-build
    proof; equal ``payload_bytes``/``file_count`` alone is not (same size
    and count can hide a rename or a same-size content swap).

    ``advisory_pyav_wheel_hash`` -- the same flag ``build()`` receives when
    ``payload_root`` was just built by this same CLI invocation -- must be
    forwarded here too: this independent re-verification is the layer that
    actually gated candidate run 32822175257 (self-hosted). Passing it only
    to the build step is not enough -- this deny-by-default provenance sweep
    runs AFTER the build, from the assembled tree on disk, and would
    otherwise re-reject the self-hosted-built ``av`` wheel on its own byte
    hash regardless of how it was authorized to build."""

    source_sha = require_source_sha(source_sha)
    payload_root = _require_real_directory(payload_root, label="app payload tree")
    if gstreamer_closure is None:
        raise AppPayloadPackBuildError(
            "GStreamer closure is required for a release app payload pack"
        )
    closure_root = _require_real_directory(gstreamer_closure, label="GStreamer closure")
    _, closure_metadata = _verified_closure_metadata(closure_root)

    verification = check_app_payload_verification(
        payload_root,
        require_caption_pack=True,
        require_console_launchers=True,
        require_dependency_wheels=True,
        advisory_pyav_wheel_hash=advisory_pyav_wheel_hash,
    )
    if verification.status != "PASS":
        raise AppPayloadPackBuildError(
            "refusing to pack an app payload tree that fails its own independent "
            f"verification:\n{verification.detail}"
        )

    manifest_path = payload_root / "app-payload-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    civiccast = manifest["civiccast"]
    civiccast_version = str(civiccast["version"])
    source_state = civiccast["source_state"]
    civiccast_source_head = require_source_sha(source_state["head"])
    if source_sha != civiccast_source_head:
        raise AppPayloadPackBuildError(
            "source SHA does not match the app payload civiccast_source_head"
        )

    composed: Path | None = None
    try:
        composed = _compose_payload_with_closure(payload_root, closure_root)
        sources = _collect_payload_sources(composed)
        result = build_native_pack(
            output=output,
            component=APP_PAYLOAD_COMPONENT,
            product_version=product_version,
            compatible_core=compatible_core or product_version,
            sources=sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={
                "civiccast_version": civiccast_version,
                "civiccast_source_head": civiccast_source_head,
                "civiccast_source_dirty": bool(source_state["dirty"]),
                "source_sha": source_sha,
                "interpreter_version": INTERPRETER_VERSION,
                "app_lock_sha256": APP_REQUIREMENTS_SHA256,
                **closure_metadata,
            },
        )
    finally:
        if composed is not None:
            rmtree(composed, ignore_errors=True)
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
        "civiccast_version": civiccast_version,
        "civiccast_source_head": civiccast_source_head,
        "civiccast_source_dirty": bool(source_state["dirty"]),
        "source_sha": source_sha,
        **closure_metadata,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--payload-root",
        type=Path,
        help=(
            "reuse an already-built app payload tree (from "
            "scripts/build_native_app_payload.py) instead of building one "
            "fresh; must already contain app-payload-manifest.json"
        ),
    )
    parser.add_argument(
        "--payload-out",
        type=Path,
        default=None,
        help=(
            "where to build the payload tree when --payload-root is not "
            "given (default: a fresh temp dir OUTSIDE the repo)"
        ),
    )
    parser.add_argument(
        "--interpreter-zip",
        type=Path,
        default=build_native_app_payload.DEFAULT_INTERPRETER_ZIP,
        help="pinned CPython embeddable zip (forwarded to the payload build)",
    )
    parser.add_argument(
        "--reviewed-pyav-wheel",
        type=Path,
        help="reuse an exact, independently reproduced PyAV wheel (forwarded to the payload build)",
    )
    parser.add_argument(
        "--msvc-runtime",
        type=Path,
        help="reviewed x64 msvcp140.dll (forwarded to the payload build)",
    )
    parser.add_argument(
        "--build-scratch",
        type=Path,
        default=None,
        help="scratch dir for the payload build (default: a temp dir)",
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="permit building the payload tree from a dirty source checkout (non-release proof only)",
    )
    parser.add_argument(
        "--advisory-pyav-wheel-hash",
        action="store_true",
        help=(
            "forwarded to the payload build: log a warning instead of failing when the "
            "compiled PyAV wheel's byte-exact hash does not match the pinned reference "
            "(every pinned download still verifies strictly). Ignored when --payload-root "
            "is given, since no PyAV build happens in that case."
        ),
    )
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--gstreamer-closure",
        required=True,
        type=Path,
        help="independently built and verified native GStreamer closure to embed",
    )
    parser.add_argument("--product-version", default=__version__)
    parser.add_argument("--compatible-core", default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--allow-development-key",
        action="store_true",
        help="explicitly allow a development-only trust root for non-release proof",
    )
    args = parser.parse_args()

    payload_out: Path | None = None
    build_scratch: Path | None = None
    try:
        require_allowed_signing_key(
            args.signing_key_id, allow_development_key=args.allow_development_key
        )
        key = load_ed25519_private_key(args.signing_private_key)

        if args.payload_root is not None:
            if args.payload_out is not None or args.build_scratch is not None:
                raise AppPayloadPackBuildError(
                    "--payload-root is mutually exclusive with --payload-out/--build-scratch"
                )
            payload_root = args.payload_root.resolve()
        else:
            payload_out = (
                args.payload_out.resolve()
                if args.payload_out is not None
                else Path(mkdtemp(prefix="civiccast-native-app-payload-pack-"))
            )
            build_scratch = (
                args.build_scratch.resolve()
                if args.build_scratch is not None
                else Path(mkdtemp(prefix="civiccast-native-app-payload-pack-scratch-"))
            )
            build_native_app_payload.build(
                out=payload_out,
                interpreter_zip=args.interpreter_zip.resolve(),
                scratch=build_scratch,
                reviewed_pyav_wheel=(
                    args.reviewed_pyav_wheel.resolve()
                    if args.reviewed_pyav_wheel is not None
                    else None
                ),
                msvc_runtime=(
                    args.msvc_runtime.resolve() if args.msvc_runtime is not None else None
                ),
                allow_dirty_source=args.allow_dirty_source,
                advisory_pyav_wheel_hash=args.advisory_pyav_wheel_hash,
            )
            payload_root = payload_out

        report = build_app_payload_pack(
            output=args.output.resolve(),
            payload_root=payload_root,
            signing_private_key=key,
            signing_key_id=args.signing_key_id,
            product_version=args.product_version,
            source_sha=args.source_sha,
            gstreamer_closure=args.gstreamer_closure.resolve(),
            compatible_core=args.compatible_core,
            advisory_pyav_wheel_hash=args.advisory_pyav_wheel_hash,
        )
    except AppPayloadPackBuildError as exc:
        print(f"build_native_app_payload_pack: {exc}", file=sys.stderr)
        return 1
    finally:
        if build_scratch is not None and args.build_scratch is None:
            rmtree(build_scratch, ignore_errors=True)

    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"app payload pack report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
