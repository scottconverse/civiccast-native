# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Fail-closed schema contract for the composed native caption-integrity proof."""

from __future__ import annotations

import hashlib
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prove_native_caption_integrity.py"


def _proof() -> object:
    if not SCRIPT.is_file():
        pytest.fail(
            "prove_native_caption_integrity.py is absent: the approved composed proof "
            "has not been implemented."
        )
    spec = spec_from_file_location("prove_native_caption_integrity", SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(
            "prove_native_caption_integrity.py is absent: the approved composed proof "
            "has not been implemented."
        )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passing_report(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path]]:
    sidecars: dict[str, Path] = {}
    receipt_channels: dict[str, dict[str, object]] = {}
    report_channels: dict[str, dict[str, object]] = {}
    for channel in ("government", "education", "public"):
        sidecar = tmp_path / "producer-output" / channel / "captions" / "active.vtt"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text(f"WEBVTT\\n\\n{channel} cue\\n", encoding="utf-8")
        evidence = tmp_path / "producer-output" / channel / "captions" / "evidence.wav"
        evidence.write_bytes(f"{channel} evidence".encode())
        sidecars[channel] = sidecar
        receipt_channels[channel] = {
            "active_vtt_path": str(sidecar),
            "active_vtt_sha256": _sha256(sidecar),
            "evidence": [{"path": str(evidence), "sha256": _sha256(evidence)}],
            "review_item_ids": [f"{channel}-review"],
        }
        report_channels[channel] = {
            "upstream_receipt_channel": channel,
            "active_vtt_path": str(sidecar),
            "active_vtt_sha256": _sha256(sidecar),
            "review_item_ids": [f"{channel}-review"],
            "evidence": [{"path": str(evidence), "sha256": _sha256(evidence)}],
            "feed_delivery": "PASS",
            "cea708_decode_back": "PASS",
            "transport_stream_sha256": "e" * 64,
        }
    producer_receipt = tmp_path / "producer-output" / "tap-asr-review-receipt.json"
    producer_receipt.write_text(
        json.dumps({"source_sha": "a" * 40, "channels": receipt_channels}, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "source_sha": "a" * 40,
        "runtime": {"python": "3.12.10", "faster_whisper": "1.2.1"},
        "model": {"model.bin": {"sha256": "b" * 64, "bytes": 3_087_284_237}},
        "upstream_producer_receipt": {
            "path": str(producer_receipt),
            "sha256": _sha256(producer_receipt),
        },
        "channels": report_channels,
    }, sidecars


class TestCaptionIntegrityProofReport:
    def test_rejects_sidecar_tampered_after_the_upstream_receipt(self, tmp_path: Path) -> None:
        report, sidecars = _passing_report(tmp_path)
        sidecars["government"].write_text("WEBVTT\\n\\nforged caption\\n", encoding="utf-8")

        assert "fabricated sidecar" in _proof().validate_caption_integrity_report(
            report,
            expected_source_sha="a" * 40,
        )

    def test_rejects_missing_required_channel_evidence_or_model_identity(
        self, tmp_path: Path
    ) -> None:
        report, _sidecars = _passing_report(tmp_path)
        del report["channels"]["public"]  # type: ignore[index]
        report["model"] = {}

        problems = _proof().validate_caption_integrity_report(report, expected_source_sha="a" * 40)

        assert any("required channels" in problem for problem in problems)
        assert any("model" in problem for problem in problems)

    def test_rejects_source_sha_feed_or_decode_back_mismatch(self, tmp_path: Path) -> None:
        report, _sidecars = _passing_report(tmp_path)
        report["source_sha"] = "f" * 40
        report["channels"]["education"]["feed_delivery"] = "MISSING"  # type: ignore[index]
        report["channels"]["public"]["cea708_decode_back"] = "FAIL"  # type: ignore[index]

        problems = _proof().validate_caption_integrity_report(report, expected_source_sha="a" * 40)

        assert any("source SHA" in problem for problem in problems)
        assert any("feed" in problem for problem in problems)
        assert any("CEA-708" in problem for problem in problems)
