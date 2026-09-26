# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11a caption FEED worker — the production caller of send_caption_cue (dedup, ON_AIR)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_feed import (
    CaptionFeedWorker,
    build_caption_feed_worker,
    cea_caption_pages,
)


def _cue(n: int, text: str) -> CaptionCue:
    return CaptionCue(
        cue_id=f"c{n}",
        start_seconds=float(n),
        end_seconds=float(n) + 1.0,
        text=text,
        confidence=1.0,
        low_confidence=False,
    )


class _Sender:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict] = []

    def __call__(
        self,
        channel_id,
        work_dir,
        *,
        text,
        pts_seconds,
        duration_seconds,
        delivery_id,
    ) -> bool:
        self.calls.append(
            {
                "channel": channel_id,
                "text": text,
                "pts": pts_seconds,
                "dur": duration_seconds,
                "delivery_id": delivery_id,
            }
        )
        return self.ok


def _worker(sender, *, on_air, cues) -> CaptionFeedWorker:
    return CaptionFeedWorker(
        work_dir=Path("/tmp/wd"),
        on_air_channels=lambda: on_air,
        caption_cue_provider=lambda _ch: cues,
        send_caption_cue=sender,
    )


def test_feed_pushes_each_cue_once_and_dedups() -> None:
    sender = _Sender()
    worker = _worker(sender, on_air=["gov"], cues=[_cue(1, "HELLO"), _cue(2, "WORLD")])
    r1 = worker.run_once()
    assert r1.cues_sent == 2
    assert [c["text"] for c in sender.calls] == ["HELLO", "WORLD"]
    assert sender.calls[0]["pts"] == 1.0
    assert sender.calls[0]["dur"] == 1.0
    # a re-scan does NOT re-push already-sent cues
    r2 = worker.run_once()
    assert r2.cues_sent == 0
    assert len(sender.calls) == 2


def test_cea_caption_pages_wrap_without_losing_words() -> None:
    pages = cea_caption_pages("The Council meeting will come to order.")

    assert pages == ("The Council meeting will come to\norder.",)
    assert " ".join(pages[0].split()) == "The Council meeting will come to order."
    assert all(len(line) <= 32 for line in pages[0].splitlines())


def test_feed_paginates_long_cue_across_cea_safe_buffers() -> None:
    sender = _Sender()
    cue = CaptionCue(
        cue_id="long",
        start_seconds=10.0,
        end_seconds=14.0,
        text="A" * 70,
        confidence=1.0,
        low_confidence=False,
    )
    worker = _worker(sender, on_air=["gov"], cues=[cue])

    result = worker.run_once()

    assert result.cues_sent == 1
    assert [call["text"] for call in sender.calls] == [
        ("A" * 32) + "\n" + ("A" * 32),
        "A" * 6,
    ]
    # A wrapped row boundary counts as one display space, as it does in
    # ordinary words. Allocate time to all displayed characters, not page count.
    boundary = 10.0 + 4.0 * 65 / 71
    assert [call["pts"] for call in sender.calls] == pytest.approx([10.0, boundary])
    assert [call["dur"] for call in sender.calls] == pytest.approx(
        [boundary - 10.0, 14.0 - boundary]
    )


def test_feed_weights_unequal_pages_within_exact_original_cue_envelope() -> None:
    sender = _Sender()
    cue = CaptionCue(
        cue_id="measured-speech",
        start_seconds=86.28,
        end_seconds=89.82,
        text="we're cool on Thursday in the low 80s with a really good chance of afternoon",
        confidence=1.0,
        low_confidence=False,
    )
    worker = _worker(sender, on_air=["gov"], cues=[cue])

    assert worker.run_once().cues_sent == 1

    weights = [len(" ".join(call["text"].split())) for call in sender.calls]
    assert weights == [56, 19]
    assert [call["dur"] for call in sender.calls] == pytest.approx([2.6432, 0.8968])
    assert sender.calls[0]["pts"] == cue.start_seconds
    for previous, following in zip(sender.calls, sender.calls[1:], strict=False):
        assert previous["pts"] + previous["dur"] == following["pts"]
    final = sender.calls[-1]
    assert final["pts"] + final["dur"] == cue.end_seconds
    assert sum(call["dur"] for call in sender.calls) == pytest.approx(
        cue.end_seconds - cue.start_seconds
    )


def test_feed_only_pushes_for_on_air_channels() -> None:
    sender = _Sender()
    worker = _worker(sender, on_air=[], cues=[_cue(1, "X")])
    result = worker.run_once()
    assert result.channels == 0
    assert result.cues_sent == 0
    assert sender.calls == []


def test_feed_does_not_mark_sent_when_send_drops() -> None:
    # FIFO not ready (or ffmpeg engine — no control FIFO): send returns False, the cue
    # is NOT marked sent, so the next scan retries it.
    sender = _Sender(ok=False)
    worker = _worker(sender, on_air=["gov"], cues=[_cue(1, "X")])
    r1 = worker.run_once()
    assert r1.cues_sent == 0
    assert r1.cues_dropped == 1
    sender.ok = True
    r2 = worker.run_once()
    assert r2.cues_sent == 1  # retried successfully


def test_feed_retries_only_unacknowledged_page_with_the_same_delivery_id() -> None:
    class _LostAckSender:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.timings: list[tuple[float, float]] = []
            self.applied: dict[str, str] = {}
            self._lose_ack_once = True

        def __call__(
            self,
            _channel_id,
            _work_dir,
            *,
            text,
            pts_seconds,
            duration_seconds,
            delivery_id,
        ) -> bool:
            self.timings.append((pts_seconds, duration_seconds))
            self.calls.append((delivery_id, text))
            self.applied.setdefault(delivery_id, text)
            if text == "A" * 6 and self._lose_ack_once:
                self._lose_ack_once = False
                return False
            return True

    sender = _LostAckSender()
    cue = CaptionCue(
        cue_id="long",
        start_seconds=10.0,
        end_seconds=14.0,
        text="A" * 70,
        confidence=1.0,
        low_confidence=False,
    )
    worker = _worker(sender, on_air=["gov"], cues=[cue])

    first = worker.run_once()
    second = worker.run_once()

    assert first.cues_sent == 0
    assert first.cues_dropped == 1
    assert second.cues_sent == 1
    assert [text for _, text in sender.calls] == [
        ("A" * 32) + "\n" + ("A" * 32),
        "A" * 6,
        "A" * 6,
    ]
    assert sender.calls[1][0] == sender.calls[2][0]
    assert sender.timings[1] == sender.timings[2]
    assert sender.timings[1][0] == pytest.approx(10.0 + 4.0 * 65 / 71)
    assert list(sender.applied.values()) == [
        ("A" * 32) + "\n" + ("A" * 32),
        "A" * 6,
    ]


def test_feed_forgets_channel_after_off_air() -> None:
    sender = _Sender()
    on_air = ["gov"]
    worker = CaptionFeedWorker(
        work_dir=Path("/tmp/wd"),
        on_air_channels=lambda: on_air,
        caption_cue_provider=lambda _ch: [_cue(1, "X")],
        send_caption_cue=sender,
    )
    assert worker.run_once().cues_sent == 1
    on_air.clear()
    assert worker.run_once().cues_sent == 0
    on_air.append("gov")
    assert worker.run_once().cues_sent == 1


def test_production_builder_uses_the_running_encoder_strategy() -> None:
    class _RunningStrategy:
        def send_caption_cue(
            self,
            channel_id,
            work_dir,
            *,
            text,
            pts_seconds,
            duration_seconds,
            delivery_id,
        ) -> bool:
            del channel_id, work_dir, text, pts_seconds, duration_seconds, delivery_id
            return True

    strategy = _RunningStrategy()

    worker = build_caption_feed_worker(
        lambda: None,
        send_caption_cue=strategy.send_caption_cue,
    )

    assert worker._send_caption_cue.__self__ is strategy


def test_feed_is_idle_while_live_captions_are_switched_off() -> None:
    # Round-2 review MAJOR 3: with the operator switch off there is no caption appsrc
    # to feed, so the loop must not read sidecars or retry cues every 2 s.
    sender = _Sender()
    reads: list[str] = []

    def _cues(channel_id: str) -> list[CaptionCue]:
        reads.append(channel_id)
        return [_cue(1, "hello")]

    worker = CaptionFeedWorker(
        work_dir=Path("/tmp/wd"),
        on_air_channels=lambda: ["gov"],
        caption_cue_provider=_cues,
        send_caption_cue=sender,
        is_enabled=lambda: False,
    )

    result = worker.run_once()

    assert result.channels == 0
    assert result.cues_sent == 0
    assert reads == []
    assert sender.calls == []


def test_feed_resumes_from_scratch_when_live_captions_are_switched_on() -> None:
    sender = _Sender()
    enabled = [True]
    worker = CaptionFeedWorker(
        work_dir=Path("/tmp/wd"),
        on_air_channels=lambda: ["gov"],
        caption_cue_provider=lambda _ch: [_cue(1, "hello")],
        send_caption_cue=sender,
        is_enabled=lambda: enabled[0],
    )
    assert worker.run_once().cues_sent == 1
    assert worker.run_once().cues_sent == 0  # deduped while on

    enabled[0] = False
    assert worker.run_once().cues_sent == 0
    enabled[0] = True  # a fresh pipeline after the switch: re-send from scratch

    assert worker.run_once().cues_sent == 1
    assert len(sender.calls) == 2


# --- U46 (2026-09-26): the sidecar the parser cannot read ------------------
#
# Public's sidecar kept growing while its emitted stream carried no captions.
# The feed parsed 0 cues, sent 0 commands, and every warning the daemon,
# strategy and engine legs own stayed silent too -- nothing below the feed ever
# saw a command. These tests pin the feed's own report of that case: a sidecar
# full of timing windows the parser cannot read is a caption fault, not an
# empty channel.

#: The exact shape public's sidecar was writing: three-digit hours, because the
#: sidecar's program clock is an absolute second count since program start.
_PUBLIC_SIDECAR = (
    "WEBVTT\n\n"
    "public-cue-101697\n"
    "112:59:50.000 --> 112:59:52.000\n"
    "Motion carries.\n\n"
    "public-cue-101698\n"
    "112:59:52.000 --> 112:59:54.310\n"
    "Second reading.\n\n"
)

#: A window that carries text but no duration: ``ffmpeg`` emits instantaneous
#: CEA-608/708 cues, and the reader skips degenerate timings rather than letting
#: CaptionCue raise. Structurally a window; nothing the parser will return.
_DEGENERATE_SIDECAR = (
    "WEBVTT\n\npublic-cue-101697\n112:59:50.000 --> 112:59:50.000\nMotion carries.\n\n"
)


def _feed_with_sidecar(sidecar: Path) -> CaptionFeedWorker:
    """A production-built feed worker whose sidecar lookup points at ``sidecar``."""

    return build_caption_feed_worker(
        lambda: None,
        send_caption_cue=_Sender(),
        work_dir=sidecar.parent,
        caption_sidecar_for=lambda _channel: sidecar,
    )


def test_feed_reads_sidecar_clock_hours_past_one_hundred(tmp_path: Path) -> None:
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text(_PUBLIC_SIDECAR, encoding="utf-8")

    cues = _feed_with_sidecar(sidecar)._caption_cue_provider("public")

    assert [cue.cue_id for cue in cues] == [
        "public-public-cue-101697",
        "public-public-cue-101698",
    ]
    assert cues[0].start_seconds == 112 * 3600 + 59 * 60 + 50.0


def test_feed_announces_a_sidecar_it_cannot_read_once_per_broken_spell(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text(_DEGENERATE_SIDECAR, encoding="utf-8")
    feed = _feed_with_sidecar(sidecar)

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.caption_feed"):
        for _ in range(3):  # a 2 s poll loop must not repeat the warning
            assert feed._caption_cue_provider("public") == []
        warnings = [record for record in caplog.records if "0 cues" in record.getMessage()]
        assert len(warnings) == 1
        assert "public" in warnings[0].getMessage()
        assert "1 timing windows" in warnings[0].getMessage()

        # The sidecar becomes readable again: no further warning, and the next
        # broken spell is announced afresh rather than suppressed by the old one.
        sidecar.write_text(_PUBLIC_SIDECAR, encoding="utf-8")
        assert len(feed._caption_cue_provider("public")) == 2
        caplog.clear()
        sidecar.write_text(_DEGENERATE_SIDECAR, encoding="utf-8")
        assert feed._caption_cue_provider("public") == []
        assert len([r for r in caplog.records if "0 cues" in r.getMessage()]) == 1


def test_feed_does_not_announce_a_sidecar_with_no_windows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text("WEBVTT\n\n", encoding="utf-8")
    feed = _feed_with_sidecar(sidecar)

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.caption_feed"):
        assert feed._caption_cue_provider("public") == []

    assert [r for r in caplog.records if "0 cues" in r.getMessage()] == []
