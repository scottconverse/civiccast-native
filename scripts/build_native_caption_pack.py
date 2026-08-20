#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the exact signed native Windows large-v3 caption component pack."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast._native_version import __version__
from civiccast.installer.native_packs import build_native_pack
from civiccast.native.app_payload import (
    CAPTION_PACK_CONTRACT,
    WHISPER_MODEL_FILES,
    WHISPER_MODEL_REPO,
    WHISPER_MODEL_REVISION,
)
from civiccast.native.caption_tiers import CAPTION_TIER_REGISTRY, FLOOR_TIER_ID, LARGE_V3_TIER_ID

FASTER_WHISPER_VERSION = "1.2.1"
CTRANSLATE2_VERSION = "4.8.1"
CAPTION_SELF_TEST_FILENAME = "jfk.wav"
CAPTION_SELF_TEST_BYTES = 352_078
CAPTION_SELF_TEST_SHA256 = "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"
CAPTION_SELF_TEST_EXPECTED_PHRASE = "and so my fellow americans"
WHISPER_LICENSE_BYTES = 1_063
WHISPER_LICENSE_SHA256 = "b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d"
SELF_TEST_LICENSE_BYTES = 1_099
SELF_TEST_LICENSE_SHA256 = "bcd8ec749126d45cb06737d0690295d73df4b6e7e194205bcf91190368f27285"


def validate_pinned_file(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    label: str,
) -> None:
    """Reject any unreviewed runtime, model, or redistributable input."""

    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    digest = hashlib.sha256()
    observed_bytes = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            observed_bytes += len(chunk)
            digest.update(chunk)
    if observed_bytes != expected_bytes:
        raise ValueError(
            f"{label} byte length mismatch: expected {expected_bytes}, observed {observed_bytes}"
        )
    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_sha256:
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, observed {observed_sha256}"
        )


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    """Load an unencrypted PEM Ed25519 signing key."""

    if not path.is_file():
        raise ValueError(f"pack signing private key is missing: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("pack signing private key must be Ed25519")
    return key


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    """Keep development trust roots out of an accidental release build."""

    if key_id.startswith("development-") and not allow_development_key:
        raise ValueError(
            "development pack signing keys require --allow-development-key; "
            "release packaging must use Scott-approved production key custody"
        )


def build_caption_pack(
    *,
    output: Path,
    model_dir: Path,
    self_test_audio: Path,
    whisper_license: Path,
    self_test_license: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    additional_tier_model_dirs: dict[str, Path] | None = None,
) -> dict[str, object]:
    """Validate pinned inputs and build the signed adaptive-tier caption pack.

    ``additional_tier_model_dirs`` maps a caption tier id (from
    :data:`civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY`, other than
    large-v3, which this function always includes) to its pinned upstream
    snapshot directory on disk. Each named tier must already be BOUND in the
    registry -- the unbound floor placeholder refuses with a clear error
    rather than silently shipping a pack that claims a tier it cannot prove.
    Today's real release invocation (``main`` below) passes none, so the
    shipped large-v3-only pack and its metadata are unchanged; this is how a
    future owner-bound floor tier is added without any structural change
    here, only a new CLI argument wiring its snapshot directory through.
    """

    # Fail fast on an unbound/unknown additional tier before spending time
    # validating the (potentially multi-gigabyte) large-v3 snapshot.
    for tier_id in sorted(additional_tier_model_dirs or {}):
        if tier_id == LARGE_V3_TIER_ID:
            raise ValueError(f"{tier_id!r} is the built-in large-v3 tier, not an additional one")
        if tier_id not in CAPTION_TIER_REGISTRY:
            raise ValueError(f"unknown caption tier: {tier_id!r}")
        CAPTION_TIER_REGISTRY[tier_id].require_bound()

    if not model_dir.is_dir():
        raise ValueError(f"pinned faster-whisper model directory is missing: {model_dir}")
    observed_model_files = {
        path.relative_to(model_dir).as_posix() for path in model_dir.rglob("*") if path.is_file()
    }
    if observed_model_files != set(WHISPER_MODEL_FILES):
        missing = sorted(set(WHISPER_MODEL_FILES) - observed_model_files)
        extra = sorted(observed_model_files - set(WHISPER_MODEL_FILES))
        raise ValueError(
            f"pinned faster-whisper model file set mismatch; missing={missing}, extra={extra}"
        )
    for filename, (expected_bytes, expected_sha256) in sorted(WHISPER_MODEL_FILES.items()):
        path = model_dir / filename
        if path.is_symlink():
            raise ValueError(f"pinned faster-whisper model file is a symlink: {filename}")
        validate_pinned_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"canonical faster-whisper large-v3 model file {filename}",
        )
    validate_pinned_file(
        self_test_audio,
        expected_bytes=CAPTION_SELF_TEST_BYTES,
        expected_sha256=CAPTION_SELF_TEST_SHA256,
        label="JFK real-audio caption self-test fixture",
    )
    validate_pinned_file(
        whisper_license,
        expected_bytes=WHISPER_LICENSE_BYTES,
        expected_sha256=WHISPER_LICENSE_SHA256,
        label="OpenAI Whisper MIT license",
    )
    validate_pinned_file(
        self_test_license,
        expected_bytes=SELF_TEST_LICENSE_BYTES,
        expected_sha256=SELF_TEST_LICENSE_SHA256,
        label="JFK self-test fixture source license",
    )

    sources = {
        f"models/faster-whisper-large-v3/{filename}": model_dir / filename
        for filename in sorted(WHISPER_MODEL_FILES)
    }
    sources.update(
        {
            f"self-test/{CAPTION_SELF_TEST_FILENAME}": self_test_audio,
            "licenses/OpenAI-Whisper-MIT.txt": whisper_license,
            "licenses/whisper.cpp-sample-MIT.txt": self_test_license,
        }
    )

    caption_tier_ids = [LARGE_V3_TIER_ID]
    for tier_id, tier_model_dir in sorted((additional_tier_model_dirs or {}).items()):
        # Already validated known/bound above; re-fetch is cheap and keeps
        # this loop the single place actual file bytes get checked.
        spec = CAPTION_TIER_REGISTRY[tier_id].require_bound()
        if not tier_model_dir.is_dir():
            raise ValueError(f"pinned {tier_id} model directory is missing: {tier_model_dir}")
        observed = {
            path.relative_to(tier_model_dir).as_posix()
            for path in tier_model_dir.rglob("*")
            if path.is_file()
        }
        if observed != set(spec.files):
            missing = sorted(set(spec.files) - observed)
            extra = sorted(observed - set(spec.files))
            raise ValueError(
                f"pinned {tier_id} model file set mismatch; missing={missing}, extra={extra}"
            )
        for filename, (expected_bytes, expected_sha256) in sorted(spec.files.items()):
            path = tier_model_dir / filename
            if path.is_symlink():
                raise ValueError(f"pinned {tier_id} model file is a symlink: {filename}")
            validate_pinned_file(
                path,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
                label=f"pinned {tier_id} model file {filename}",
            )
            sources[f"models/{spec.model_directory}/{filename}"] = path
        caption_tier_ids.append(tier_id)

    notice = (
        "CivicCast native caption pack\n"
        f"Runtime: faster-whisper {FASTER_WHISPER_VERSION} with "
        f"CTranslate2 {CTRANSLATE2_VERSION} from the required Core pack\n"
        f"Model: {WHISPER_MODEL_REPO}@{WHISPER_MODEL_REVISION}\n"
        "Model architecture: OpenAI Whisper large-v3\n"
        "Conversion: canonical SYSTRAN CTranslate2 large-v3 revision; "
        "no smaller model and no GGML quantization\n"
        f"Activation self-test audio: {CAPTION_SELF_TEST_FILENAME}\n"
        f"Activation self-test audio SHA-256: {CAPTION_SELF_TEST_SHA256}\n"
        f"Expected self-test phrase: {CAPTION_SELF_TEST_EXPECTED_PHRASE}\n"
        "Runtime backend: CPU faster-whisper, local-files-only\n"
    )
    with TemporaryDirectory(prefix="civiccast-caption-pack-") as temporary:
        notice_path = Path(temporary) / "NOTICE.txt"
        notice_path.write_text(notice, encoding="utf-8", newline="\n")
        sources["notices/caption-runtime.txt"] = notice_path
        result = build_native_pack(
            output=output,
            component="captions-large-v3",
            product_version=product_version,
            compatible_core=product_version,
            sources=sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={
                **CAPTION_PACK_CONTRACT,
                "self_test_expected_phrase": CAPTION_SELF_TEST_EXPECTED_PHRASE,
                "caption_tiers": caption_tier_ids,
            },
        )
    public_key = signing_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "component": result.component,
        "file_count": result.file_count,
        "output": str(result.path),
        "pack_bytes": result.path.stat().st_size,
        "pack_sha256": result.sha256,
        "payload_bytes": result.total_bytes,
        "product_version": result.product_version,
        "public_key_base64": base64.b64encode(public_key).decode("ascii"),
        "signing_key_id": result.signing_key_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--self-test-audio", required=True, type=Path)
    parser.add_argument("--whisper-license", required=True, type=Path)
    parser.add_argument("--self-test-license", required=True, type=Path)
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--product-version", default=__version__)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--allow-development-key",
        action="store_true",
        help="explicitly allow a development-only trust root for non-release proof",
    )
    parser.add_argument(
        "--floor-model-dir",
        type=Path,
        default=None,
        help=(
            "pinned upstream snapshot directory for the caption FLOOR tier "
            f"({CAPTION_TIER_REGISTRY[FLOOR_TIER_ID].model_repository}, the mandatory "
            "CPU-only baseline bound by OWNER-DECISION-caption-adaptive-tier.md). "
            "When given, the built pack carries the floor tier alongside large-v3; "
            "when omitted, the pack is large-v3-only (today's unchanged default)."
        ),
    )
    args = parser.parse_args()
    require_allowed_signing_key(
        args.signing_key_id,
        allow_development_key=args.allow_development_key,
    )
    key = load_ed25519_private_key(args.signing_private_key)
    additional_tier_model_dirs = (
        {FLOOR_TIER_ID: args.floor_model_dir.resolve()}
        if args.floor_model_dir is not None
        else None
    )
    report = build_caption_pack(
        output=args.output.resolve(),
        model_dir=args.model_dir.resolve(),
        self_test_audio=args.self_test_audio.resolve(),
        whisper_license=args.whisper_license.resolve(),
        self_test_license=args.self_test_license.resolve(),
        signing_private_key=key,
        signing_key_id=args.signing_key_id,
        product_version=args.product_version,
        additional_tier_model_dirs=additional_tier_model_dirs,
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"caption pack report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
