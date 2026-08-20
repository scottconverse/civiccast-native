#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Provision the pinned CAPTIONS-FLOOR bundle root that
``scripts/build_native_station_bundle.py``'s ``--captions-floor-root`` consumes.

## The gap this closes

``scripts/build_native_caption_pack.py`` already downloads and hash-verifies
the floor tier's upstream snapshot (``Systran/faster-whisper-medium``, pinned
in ``civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY``) via
``civiccast.installer.model_download._download_floor_caption_model`` -- and
the JFK self-test fixture's identity
(``CAPTION_SELF_TEST_FILENAME``/``_BYTES``/``_SHA256``) is already pinned
there too -- but nothing in this repository has ever DOWNLOADED that fixture:
every existing caller (including the caption pack builder's own CLI,
``--self-test-audio``) has always required a caller-supplied path to bytes
that were assumed to already be on disk. This script closes both gaps for
CI: it reconstructs the EXACT directory shape
``scripts/build_native_station_bundle.py``'s ``--captions-floor-root``
docstring pins (``models/faster-whisper-medium/{config.json,model.bin,
tokenizer.json,vocabulary.txt}`` + ``self-test/jfk.wav``), hash-verifying
every byte against the SAME pinned identities the caption pack builder and
its Rust-side verifier already trust -- never a second, independently
invented pin.

## Provenance of the JFK fixture's pinned bytes

``CAPTION_SELF_TEST_BYTES``/``CAPTION_SELF_TEST_SHA256`` below are mirrored
VERBATIM from ``scripts/build_native_caption_pack.py`` (352,078 bytes,
sha256 ``59dfb9a4...``). Confirmed byte-for-byte against
``ggerganov/whisper.cpp``'s own ``samples/jfk.wav``: that file has exactly
ONE commit in its entire history,
``b0a11594aec50892a02cd8d129eee2dfe93a8bb8`` ("Initial release",
2022-09-25), so this script pins that exact commit SHA in its download URL
rather than a mutable branch ref -- the same "pin the commit, never a
branch" posture ``civiccast.installer.model_download.WHISPER_MODEL_REVISION``
already applies to the Whisper snapshots themselves. The downloaded bytes
are re-verified against the pinned size/hash below regardless of what the
source claims, so a compromised or redirected source fails closed rather
than silently shipping different bytes.

## Reuse, not a fork

The floor tier's own repository/revision/file identities are never
re-typed here: they come from
``civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY[FLOOR_TIER_ID]``, the
single source of truth also used by the caption pack builder and its
verifier. Only the JFK fixture's identity is locally pinned, because no
existing module owns it as an importable constant (the same duplication
posture ``civiccast.installer.model_download`` already accepts for the
Whisper large-v3 repo/revision, which is ALSO pinned independently in
``civiccast.native.app_payload``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.native.caption_tiers import CAPTION_TIER_REGISTRY, FLOOR_TIER_ID  # noqa: E402

_CHUNK_BYTES: Final[int] = 1024 * 1024
_REPARSE_POINT: Final[int] = 0x400

#: Mirrored VERBATIM from scripts/build_native_caption_pack.py -- kept in
#: lockstep with that module's identical constants, never re-derived. See
#: this module's docstring for the pinned-commit provenance.
CAPTION_SELF_TEST_FILENAME: Final[str] = "jfk.wav"
CAPTION_SELF_TEST_BYTES: Final[int] = 352_078
CAPTION_SELF_TEST_SHA256: Final[str] = (
    "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"
)
#: whisper.cpp's samples/jfk.wav has exactly one commit in its entire
#: history -- pin THAT commit, never a mutable branch ref.
_JFK_SOURCE_COMMIT: Final[str] = "b0a11594aec50892a02cd8d129eee2dfe93a8bb8"
_JFK_SOURCE_URL: Final[str] = (
    f"https://raw.githubusercontent.com/ggerganov/whisper.cpp/{_JFK_SOURCE_COMMIT}/samples/jfk.wav"
)

DEFAULT_CACHE: Final[Path] = ROOT / "build" / "native-model-cache-captions-floor"
DEFAULT_OUTPUT: Final[Path] = ROOT / "build" / "native-captions-floor-root"


class CaptionFloorProvisionError(RuntimeError):
    """The pinned captions-floor bundle root could not be reconstructed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise CaptionFloorProvisionError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CaptionFloorProvisionError(f"{label} must not be a symbolic link")
    if getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
        raise CaptionFloorProvisionError(f"{label} must not be a reparse point")
    if not stat.S_ISREG(metadata.st_mode):
        raise CaptionFloorProvisionError(f"{label} must be a regular file")


def _verify_file(path: Path, *, expected_bytes: int, expected_sha256: str, label: str) -> None:
    _require_regular_file(path, label=label)
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise CaptionFloorProvisionError(
            f"{label} size {actual_bytes} != reviewed {expected_bytes}"
        )
    actual_sha256 = _sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise CaptionFloorProvisionError(
            f"{label} SHA-256 {actual_sha256} != reviewed {expected_sha256}"
        )


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def fetch_jfk_self_test_audio(
    cache: Path,
    *,
    offline: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
    """Fetch the pinned JFK self-test fixture into ``cache``, verifying it
    against the SAME identity ``scripts/build_native_caption_pack.py``
    pins."""

    destination = cache / CAPTION_SELF_TEST_FILENAME
    label = "JFK real-audio caption self-test fixture"
    if destination.exists():
        _verify_file(
            destination,
            expected_bytes=CAPTION_SELF_TEST_BYTES,
            expected_sha256=CAPTION_SELF_TEST_SHA256,
            label=label,
        )
        return destination
    if offline:
        raise CaptionFloorProvisionError(f"offline cache is missing {label}: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        _JFK_SOURCE_URL,
        headers={"User-Agent": "CivicCast-native-caption-floor-provisioner/1"},
    )
    try:
        with opener(request, timeout=60) as response, partial.open("xb") as output:
            observed = 0
            while chunk := response.read(_CHUNK_BYTES):
                observed += len(chunk)
                if observed > CAPTION_SELF_TEST_BYTES:
                    raise CaptionFloorProvisionError(f"{label} exceeds reviewed size")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        _verify_file(
            partial,
            expected_bytes=CAPTION_SELF_TEST_BYTES,
            expected_sha256=CAPTION_SELF_TEST_SHA256,
            label=label,
        )
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def fetch_floor_model_snapshot(cache: Path, *, offline: bool = False) -> Path:
    """Fetch the pinned ``Systran/faster-whisper-medium`` snapshot into
    ``cache`` via ``huggingface_hub`` -- the SAME mechanism
    ``civiccast.installer.model_download._download_floor_caption_model``
    uses -- then hash-verify every file against
    ``CAPTION_TIER_REGISTRY[FLOOR_TIER_ID].files``. ``huggingface_hub``'s own
    integrity checking is real but is not OUR pin; this is the "never fetch
    unpinned bytes" enforcement point for this script."""

    spec = CAPTION_TIER_REGISTRY[FLOOR_TIER_ID].require_bound()
    local_dir = cache / spec.model_directory

    if offline:
        if not local_dir.is_dir():
            raise CaptionFloorProvisionError(
                f"offline cache is missing the floor tier snapshot: {local_dir}"
            )
    else:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:  # pragma: no cover - environment guard
            raise CaptionFloorProvisionError(
                "huggingface_hub is required to provision the caption floor tier; "
                "install the captions-runtime extra"
            ) from exc
        # require_bound() guarantees a non-None pinned repository/revision;
        # narrow the Optional for mypy the same way
        # civiccast.installer.model_download.download_release_models does
        # for this identical field.
        repository = spec.model_repository
        revision = spec.model_revision
        assert repository is not None
        assert revision is not None
        snapshot_download(  # nosec B615 - revision is pinned via caption_tiers.py.
            repo_id=repository,
            revision=revision,
            local_dir=str(local_dir),
            allow_patterns=sorted(spec.files),
        )

    observed = {path.name for path in local_dir.iterdir() if path.is_file()}
    expected = set(spec.files)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise CaptionFloorProvisionError(
            f"floor tier snapshot file set mismatch; missing={missing}, extra={extra}"
        )
    for filename, (expected_bytes, expected_sha256) in sorted(spec.files.items()):
        path = local_dir / filename
        if path.is_symlink():
            raise CaptionFloorProvisionError(f"floor tier snapshot file is a symlink: {filename}")
        _verify_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"pinned floor tier model file {filename}",
        )
    return local_dir


def build_captions_floor_root(
    *,
    output: Path,
    cache: Path = DEFAULT_CACHE,
    offline: bool = False,
) -> Path:
    """Assemble the exact ``--captions-floor-root`` shape
    ``scripts/build_native_station_bundle.py`` requires: ``models/
    faster-whisper-medium/*`` + ``self-test/jfk.wav``, every byte hash-
    verified against the SAME pins the caption pack builder and its
    Rust-side verifier already trust. Fails loud, before writing anything
    real, if either pinned source cannot be reconstructed (never a partial
    bundle root on disk -- same temp-dir-then-replace promotion as
    ``provision_native_ollama_models.py::stage_model``)."""

    spec = CAPTION_TIER_REGISTRY[FLOOR_TIER_ID].require_bound()
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise CaptionFloorProvisionError(
            f"refusing non-empty captions-floor-root output directory: {output}"
        )

    model_source = fetch_floor_model_snapshot(cache, offline=offline)
    audio_source = fetch_jfk_self_test_audio(cache, offline=offline)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".staging", dir=output.parent)
    )
    try:
        model_dest_dir = temporary / "models" / spec.model_directory
        for filename in sorted(spec.files):
            _link_or_copy(model_source / filename, model_dest_dir / filename)
        self_test_dir = temporary / "self-test"
        _link_or_copy(audio_source, self_test_dir / CAPTION_SELF_TEST_FILENAME)

        if output.exists():
            output.rmdir()
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_captions_floor_root(
            output=args.output,
            cache=args.cache,
            offline=args.offline,
        )
    except CaptionFloorProvisionError as exc:
        print(f"provision_native_caption_floor_root: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "output": str(result)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
