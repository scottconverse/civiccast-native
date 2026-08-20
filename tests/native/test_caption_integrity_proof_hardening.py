# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Additional fail-closed checks for the composed caption-integrity receipt."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from tests.native.test_caption_integrity_proof import _passing_report, _proof


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_report(tmp_path: Path) -> dict[str, object]:
    from civiccast.native.app_payload import CAPTION_PACK_CONTRACT, WHISPER_MODEL_FILES

    report, _sidecars = _passing_report(tmp_path)
    report["runtime"] = {
        "backend": "faster-whisper",
        "runtime_version": CAPTION_PACK_CONTRACT["runtime_version"],
        "ctranslate2_version": CAPTION_PACK_CONTRACT["ctranslate2_version"],
        "device": CAPTION_PACK_CONTRACT["runtime_device"],
        "compute_type": CAPTION_PACK_CONTRACT["runtime_compute_type"],
    }
    report["model"] = {
        name: {"bytes": bytes_, "sha256": digest}
        for name, (bytes_, digest) in WHISPER_MODEL_FILES.items()
    }
    for channel in report["channels"].values():  # type: ignore[index,union-attr]
        stream = tmp_path / f"{channel['upstream_receipt_channel']}.ts"  # type: ignore[index]
        stream.write_bytes(b"real emitted transport stream")
        channel["transport_stream_path"] = str(stream)  # type: ignore[index]
        channel["transport_stream_bytes"] = stream.stat().st_size  # type: ignore[index]
        channel["transport_stream_sha256"] = _sha256(stream)  # type: ignore[index]
    return report


def test_rejects_runtime_model_and_emitted_stream_not_bound_to_signed_contract(
    tmp_path: Path,
) -> None:
    report = _accepted_report(tmp_path)
    report["runtime"]["device"] = "cuda"  # type: ignore[index]
    report["model"]["model.bin"]["sha256"] = "0" * 64  # type: ignore[index]
    report["channels"]["government"]["transport_stream_sha256"] = "f" * 64  # type: ignore[index]

    problems = _proof().validate_caption_integrity_report(report, expected_source_sha="a" * 40)

    assert any("runtime identity" in problem for problem in problems)
    assert any("model identity" in problem for problem in problems)
    assert any("transport stream" in problem for problem in problems)


def test_refuses_a_dirty_source_tree_before_claiming_head_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = _proof()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["git", "status", "--porcelain"]
        return subprocess.CompletedProcess(
            command, 0, stdout=" M scripts/prove_native_caption_integrity.py\n"
        )

    monkeypatch.setattr(proof.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="dirty source tree"):
        proof._git_source_sha()
