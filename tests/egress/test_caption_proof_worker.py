# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11a caption decode-back proof loop (run_once logic + live-capture selection)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_proof_worker import (
    CaptionProofWorker,
    _emitted_stream_target,
    capture_emitted_segment,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec, EgressStateRow
from civiccast.egress.store import InMemoryEgressStore

_SRT = "1\n00:00:00,200 --> 00:00:01,500\nHELLO CIVICCAST\n"


def _cue(text: str = "HELLO CIVICCAST") -> CaptionCue:
    return CaptionCue(
        cue_id="c1",
        start_seconds=0.2,
        end_seconds=1.5,
        text=text,
        confidence=1.0,
        low_confidence=False,
    )


def _runner(stdout: str = "", returncode: int = 0) -> Any:
    return lambda _args: SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def _clock() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _worker(
    store: InMemoryEgressStore, *, expected, runner, segment: Path | None
) -> CaptionProofWorker:
    return CaptionProofWorker(
        store=store,
        on_air_channels=lambda: ["gov"],
        capture_segment=lambda _ch: segment,
        expected_cues_provider=lambda _ch: expected,
        runner=runner,
        clock=_clock,
    )


def test_worker_persists_pass_for_matching_captions(tmp_path) -> None:
    store = InMemoryEgressStore()
    seg = tmp_path / "seg.ts"
    seg.write_bytes(b"x")
    worker = _worker(store, expected=[_cue()], runner=_runner(_SRT), segment=seg)
    result = worker.run_once()
    assert result.passed == 1
    assert result.failed == 0
    sample = store.latest_caption_proof_sample("gov")
    assert sample is not None
    assert sample.status == "PASS"
    assert sample.caption_status == "on"
    assert sample.mode == "cea-708"


def test_worker_fails_when_captions_do_not_survive(tmp_path) -> None:
    store = InMemoryEgressStore()
    seg = tmp_path / "seg.ts"
    seg.write_bytes(b"x")
    # decode-back returns no captions (empty stdout) → FAIL, fail-closed not-verified
    worker = _worker(store, expected=[_cue()], runner=_runner(""), segment=seg)
    result = worker.run_once()
    assert result.passed == 0
    assert result.failed == 1
    sample = store.latest_caption_proof_sample("gov")
    assert sample.status == "FAIL"
    assert sample.caption_status == "not-verified"


def test_worker_skips_when_no_segment_captured() -> None:
    store = InMemoryEgressStore()
    worker = _worker(store, expected=[_cue()], runner=_runner(_SRT), segment=None)
    result = worker.run_once()
    assert result.skipped_no_capture == 1
    assert result.scanned == 0
    # nothing persisted → caption_status stays not-verified (fail-closed)
    assert store.latest_caption_proof_sample("gov") is None


def test_worker_fail_closed_when_no_expected_cues(tmp_path) -> None:
    store = InMemoryEgressStore()
    seg = tmp_path / "seg.ts"
    seg.write_bytes(b"x")
    # even if the stream HAS captions, no expected cues never fabricates a PASS
    worker = _worker(store, expected=[], runner=_runner(_SRT), segment=seg)
    result = worker.run_once()
    assert result.failed == 1
    sample = store.latest_caption_proof_sample("gov")
    assert sample.status == "FAIL"
    assert sample.caption_status == "not-verified"
    assert sample.blocker == "EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES"


# --- live-capture target selection (the WSL/LPM edge's pure parts) --------------


def _config(*sinks: EgressSinkSpec) -> EgressConfig:
    return EgressConfig(channel_id="gov", enabled=True, slate_message="x", sinks=list(sinks))


def test_emitted_stream_target_prefers_file_sink() -> None:
    store = InMemoryEgressStore()
    store.upsert_config(
        _config(
            EgressSinkSpec(kind="udp-ts", label="head", uri="udp://239.0.0.9:5000"),
            EgressSinkSpec(kind="file", label="cap", uri="file:///tmp/gov.ts"),
        )
    )
    assert _emitted_stream_target(store, "gov") == ("/tmp/gov.ts", True)


def test_emitted_stream_target_falls_back_to_udp() -> None:
    store = InMemoryEgressStore()
    store.upsert_config(
        _config(EgressSinkSpec(kind="udp-ts", label="head", uri="udp://239.0.0.9:5000"))
    )
    assert _emitted_stream_target(store, "gov") == ("udp://239.0.0.9:5000", False)


def test_emitted_stream_target_none_for_non_ts_sinks() -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config(EgressSinkSpec(kind="sdi", label="sdi", uri="decklink://0")))
    assert _emitted_stream_target(store, "gov") is None
    assert _emitted_stream_target(store, "missing") is None


def test_capture_returns_none_when_runner_produces_no_bytes(tmp_path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(
        _config(EgressSinkSpec(kind="udp-ts", label="head", uri="udp://239.0.0.9:5000"))
    )
    # runner "succeeds" but writes nothing → None (so the channel is skipped, not a false PASS)
    captured = capture_emitted_segment(store, "gov", work_dir=tmp_path, runner=_runner(""))
    assert captured is None


def test_on_air_filter_via_store_state() -> None:
    # the wired on_air filter only samples ON_AIR channels
    store = InMemoryEgressStore()
    store.upsert_config(_config(EgressSinkSpec(kind="file", label="f", uri="file:///tmp/gov.ts")))
    store.write_state(
        EgressStateRow(
            channel_id="gov", state="STOPPED", updated_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
    )
    on_air = [
        c.channel_id
        for c in store.list_configs()
        if (row := store.read_state(c.channel_id)) is not None and row.state == "ON_AIR"
    ]
    assert on_air == []
