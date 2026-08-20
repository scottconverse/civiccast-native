# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the live caption path proof harness."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_FFMPEG_MISSING = shutil.which("ffmpeg") is None
_FFMPEG_SKIP_REASON = "ffmpeg must be on PATH to generate the live caption proof source"


def _load_run_proof() -> Any:
    script_path = Path(__file__).parents[2] / "scripts" / "prove-live-caption-path.py"
    spec = importlib.util.spec_from_file_location("prove_live_caption_path", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run_proof


@pytest.mark.skipif(_FFMPEG_MISSING, reason=_FFMPEG_SKIP_REASON)
def test_live_caption_proof_writes_hls_and_blocks_retroactive_rewrite(tmp_path: Path) -> None:
    run_proof = _load_run_proof()
    result = run_proof(output_dir=tmp_path / "hls", latency_budget_seconds=4.0)

    assert result.passed is True
    assert result.window_count == 1
    assert result.first_pass_committed_count == 0
    assert result.second_pass_committed_count == 1
    assert result.review_item_count == 1
    assert result.manifest_has_subtitle_track is True
    assert result.caption_segment_has_text is True
    assert result.no_retroactive_rewrite is True


@pytest.mark.skipif(_FFMPEG_MISSING, reason=_FFMPEG_SKIP_REASON)
def test_live_caption_proof_can_run_multi_window_soak(tmp_path: Path) -> None:
    run_proof = _load_run_proof()
    result = run_proof(output_dir=tmp_path / "hls", latency_budget_seconds=4.0, window_count=3)

    assert result.passed is True
    assert result.window_count == 3
    assert result.first_pass_committed_count == 0
    assert result.second_pass_committed_count == 3
    assert result.review_item_count == 3
