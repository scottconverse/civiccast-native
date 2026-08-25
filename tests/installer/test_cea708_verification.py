# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit + integration tests for civiccast.installer.cea708_verification (S11 -> S3).

The embed leg (real GStreamer worker subprocess) and the decode leg (real ffmpeg)
are tested at different tiers, matching how they were built and verified:

* The decode leg is exercised against a REAL, committed MPEG-TS fixture with
  genuine embedded CEA-608-in-708 SEI data (see
  ``tests/egress/fixtures/cea708_test_caption.mpegts`` and
  ``tests/egress/test_caption_proof.py``) via an injected ``embed_runner`` fake
  that just returns that fixture's path -- so ``verify_cea708_decode_back``'s
  decode-and-compare logic is proven against real decoder output here, with only
  the (untestable-without-GStreamer) embed half faked.
* The full embed-through-decode-back round trip via the real GStreamer worker
  subprocess is exercised by ``test_run_gst_caption_embed_test_pattern_real_worker``,
  marked ``integration`` and skipped unless the bundled GStreamer Python bindings
  (``gi``) are importable -- this dev/CI sandbox does not carry them; a native
  Windows box with the packaged runtime (or the WSL/system-GStreamer dev tier) does.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from civiccast.installer.cea708_verification import (
    TEST_CAPTION_TEXT,
    verify_cea708_decode_back,
    write_test_caption_sidecar,
)

_FIXTURES_DIR = Path(__file__).parent.parent / "egress" / "fixtures"
_REAL_CAPTION_FIXTURE = _FIXTURES_DIR / "cea708_test_caption.mpegts"
_NO_CAPTION_FIXTURE = _FIXTURES_DIR / "cea708_no_captions.mpegts"

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="needs the real ffmpeg decode-back path"
)
requires_gstreamer = pytest.mark.skipif(
    importlib.util.find_spec("gi") is None,
    reason="needs the bundled GStreamer Python bindings (gi) to run the real worker",
)


def test_write_test_caption_sidecar_produces_valid_webvtt(tmp_path: Path) -> None:
    path = write_test_caption_sidecar(
        tmp_path / "test.vtt", text="HELLO", start_seconds=1.0, end_seconds=3.5
    )
    content = path.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:03.500" in content
    assert "HELLO" in content


def test_write_test_caption_sidecar_rejects_non_positive_duration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="end_seconds"):
        write_test_caption_sidecar(tmp_path / "test.vtt", start_seconds=2.0, end_seconds=2.0)


@requires_ffmpeg
def test_verify_cea708_decode_back_true_against_the_real_fixture(tmp_path: Path) -> None:
    """The embed leg is faked (returns the real, pre-built fixture); the decode leg
    is 100% real ffmpeg -- proving the full compare-and-report logic end to end."""

    def fake_embed_runner(
        sidecar_path: Path, duration_seconds: int, muxrate_kbps: int, work_dir: Path
    ) -> Path:
        assert sidecar_path.exists()
        return _REAL_CAPTION_FIXTURE

    # The fixture's caption is genuinely embedded at [0.0, 1.6]s (see its module
    # docstring / test_caption_proof.py) -- duration_seconds=2 makes
    # verify_cea708_decode_back's own expected-cue window ([0.5, 1.5]s) land within
    # its 0.75s timing tolerance of that real, fixed timing.
    result = verify_cea708_decode_back(
        duration_seconds=2,
        work_dir=tmp_path,
        embed_runner=fake_embed_runner,
        text="CIVICCAST CEA708 TEST.",
    )
    assert result.verified is True
    assert result.blocker is None
    assert "CIVICCAST CEA708 TEST." in result.decoded_text
    assert result.expected_text == "CIVICCAST CEA708 TEST."


@requires_ffmpeg
def test_verify_cea708_decode_back_false_when_nothing_was_embedded(tmp_path: Path) -> None:
    """Same real ffmpeg decode leg, but the emitted stream never actually carried
    the caption (fixture with no embedded captions) -- must report False, never a
    fabricated True."""

    def fake_embed_runner(
        sidecar_path: Path, duration_seconds: int, muxrate_kbps: int, work_dir: Path
    ) -> Path:
        return _NO_CAPTION_FIXTURE

    result = verify_cea708_decode_back(
        duration_seconds=8,
        work_dir=tmp_path,
        embed_runner=fake_embed_runner,
    )
    assert result.verified is False
    assert result.blocker is not None
    assert result.decoded_text == ""


def test_verify_cea708_decode_back_false_when_embed_raises(tmp_path: Path) -> None:
    """Fail-closed: an embed-side exception (e.g. GStreamer engine/plugins not
    present) is caught and reported as verified=False, never propagated as a crash
    and never silently swallowed into a fabricated True."""

    def failing_embed_runner(
        sidecar_path: Path, duration_seconds: int, muxrate_kbps: int, work_dir: Path
    ) -> Path:
        raise RuntimeError("GStreamer engine not present on this box")

    result = verify_cea708_decode_back(
        duration_seconds=8,
        work_dir=tmp_path,
        embed_runner=failing_embed_runner,
    )
    assert result.verified is False
    assert "GStreamer engine not present" in result.detail
    assert result.blocker is not None and "CEA708_EMBED_FAILED" in result.blocker


def test_verify_cea708_decode_back_false_when_decode_runner_raises(tmp_path: Path) -> None:
    """Fail-closed on the decode side too: the embed leg succeeds (fake), but the
    decode runner itself blows up -- still reported False, not raised."""

    def fake_embed_runner(
        sidecar_path: Path, duration_seconds: int, muxrate_kbps: int, work_dir: Path
    ) -> Path:
        return _REAL_CAPTION_FIXTURE

    def failing_decode_runner(args: list[str]) -> object:
        raise RuntimeError("ffmpeg not found")

    result = verify_cea708_decode_back(
        duration_seconds=8,
        work_dir=tmp_path,
        embed_runner=fake_embed_runner,
        decode_runner=failing_decode_runner,  # type: ignore[arg-type]
    )
    assert result.verified is False
    assert result.blocker is not None and "CEA708_DECODE_FAILED" in result.blocker


def test_verify_cea708_decode_back_default_text_is_deterministic() -> None:
    assert TEST_CAPTION_TEXT == "CIVICCAST CEA-708 COMMISSIONING TEST"


@pytest.mark.integration
@requires_gstreamer
def test_run_gst_caption_embed_test_pattern_real_worker(tmp_path: Path) -> None:
    """Full real round trip: the actual GStreamer worker subprocess embeds the test
    caption via the product's real sidecar embed leg, then real ffmpeg decodes it
    back. Only runs where the bundled GStreamer Python bindings are importable."""
    from civiccast.installer.cea708_verification import run_gst_caption_embed_test_pattern

    sidecar = write_test_caption_sidecar(tmp_path / "test.vtt")
    result = verify_cea708_decode_back(
        duration_seconds=6,
        work_dir=tmp_path,
        embed_runner=run_gst_caption_embed_test_pattern,
    )
    assert result.verified is True, result.detail
    assert sidecar.exists()
