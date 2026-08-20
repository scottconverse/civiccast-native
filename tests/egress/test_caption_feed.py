# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11a caption FEED worker — the production caller of send_caption_cue (dedup, ON_AIR)."""

from __future__ import annotations

from pathlib import Path

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
    assert [call["pts"] for call in sender.calls] == [10.0, 12.0]
    assert [call["dur"] for call in sender.calls] == [2.0, 2.0]


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
            del pts_seconds, duration_seconds
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
