# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic live WebVTT publication tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import civiccast.captions.live_sidecar as sidecar_module
from civiccast.captions.live_sidecar import (
    LiveWebVttPublisher,
    publish_caption_runtime_status,
    reset_existing_live_sidecars,
)
from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text


def _cue(text: str) -> CaptionCue:
    return CaptionCue(
        cue_id="cue-1",
        start_seconds=1.0,
        end_seconds=3.0,
        text=text,
        confidence=0.91,
    )


def test_publishes_complete_webvtt_atomically(tmp_path: Path) -> None:
    active = tmp_path / "gov" / "captions" / "active.vtt"
    publisher = LiveWebVttPublisher(active)

    publisher.publish([_cue("motion carries")])

    cues = load_caption_cues_from_timed_text(active, source_id="gov")
    assert [(cue.text, cue.start_seconds, cue.end_seconds) for cue in cues] == [
        ("motion carries", 1.0, 3.0)
    ]
    assert list(active.parent.glob("*.tmp")) == []


def test_failed_replace_preserves_the_prior_complete_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = tmp_path / "gov" / "captions" / "active.vtt"
    publisher = LiveWebVttPublisher(active)
    publisher.publish([_cue("old complete cue")])
    before = active.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(sidecar_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        publisher.publish([_cue("partial replacement must not leak")])

    assert active.read_bytes() == before
    assert list(active.parent.glob("*.tmp")) == []


def test_worker_restart_resets_only_active_sidecars(tmp_path: Path) -> None:
    active = tmp_path / "gov" / "captions" / "active.vtt"
    publisher = LiveWebVttPublisher(active)
    publisher.publish([_cue("stale cue")])
    retained = active.parent / "evidence" / "retained.wav"
    retained.parent.mkdir()
    retained.write_bytes(b"retained")

    reset_existing_live_sidecars(tmp_path)

    assert load_caption_cues_from_timed_text(active, source_id="gov") == []
    assert retained.read_bytes() == b"retained"


def test_storage_refusal_clears_stale_active_vtt_and_records_the_refusal(tmp_path: Path) -> None:
    active = tmp_path / "gov" / "captions" / "active.vtt"
    LiveWebVttPublisher(active).publish([_cue("stale caption")])

    status = publish_caption_runtime_status(
        tmp_path,
        "gov",
        state="storage-refused",  # type: ignore[arg-type]
        backlog_segments=0,
        max_backlog_segments=2,
        refusal_reason="free-space-reserve-unrestorable",
    )

    assert load_caption_cues_from_timed_text(active, source_id="gov") == []
    payload = __import__("json").loads(status.read_text(encoding="utf-8"))
    assert payload["state"] == "storage-refused"
    assert payload["refusal_reason"] == "free-space-reserve-unrestorable"
