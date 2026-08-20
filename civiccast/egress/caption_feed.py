# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live caption FEED worker (S11a) — the production caller of send_caption_cue.

The S11a embed lane (appsrc -> tttocea608 -> cccombiner -> h264ccinserter) is only
useful if something pushes timed-text cues into the live appsrc. This worker is that
producer: for each ON_AIR channel that embeds captions, it reads the channel's active
caption cues (the same sidecar the decode-back proof reads as "expected") and pushes
each NEW cue to the running gst worker via ``GstPlayoutStrategy.send_caption_cue`` (the
``caption`` control command). Already-pushed cues are tracked so a re-scan never
double-sends. On the ffmpeg engine there is no control FIFO, so the send simply drops
(captions embed only on the gst engine — documented).

The cue PTS->pipeline-running-time alignment is the live edge (WSL/LPM-validated); the
scan/dedup/feed logic is unit-tested here. This closes the loop the decode-back proof
verifies: sidecar cues -> feed -> embed -> emitted stream -> decode-back -> caption_status.
"""

from __future__ import annotations

import logging
import textwrap
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text

_LOG = logging.getLogger(__name__)

OnAirChannelsProvider = Callable[[], list[str]]
CaptionCueProvider = Callable[[str], list[CaptionCue]]
# (channel_id, work_dir, *, text, pts_seconds, duration_seconds) -> sent?
SendCaptionCue = Callable[..., bool]
SessionFactory = Callable[[], AbstractContextManager[Session]]

_CEA_COLUMNS = 32
_CEA_ROWS_PER_PAGE = 2
_CAPTION_DELIVERY_NAMESPACE = uuid.UUID("e0adb299-d51d-4f2e-b47b-c9eefc1a9046")


def cea_caption_pages(text: str) -> tuple[str, ...]:
    """Return lossless CEA-608-safe display pages for one machine cue.

    CEA-608 rows are 32 columns wide. ``tttocea608`` truncates a longer
    unbroken row rather than preserving the overflow, so the feed must insert
    row breaks before handing text to GStreamer. Longer cues are paginated in
    two-row displays; no source word is silently discarded.
    """

    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("caption text must contain visible characters")
    lines = textwrap.wrap(
        normalized,
        width=_CEA_COLUMNS,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
        replace_whitespace=True,
    )
    return tuple(
        "\n".join(lines[index : index + _CEA_ROWS_PER_PAGE])
        for index in range(0, len(lines), _CEA_ROWS_PER_PAGE)
    )


def caption_page_delivery_id(
    channel_id: str,
    cue_id: str,
    page_index: int,
) -> str:
    """Return the stable worker-envelope id for one cue display page."""
    if not channel_id or not cue_id or page_index < 0:
        raise ValueError("caption page delivery identity is invalid")
    return str(
        uuid.uuid5(
            _CAPTION_DELIVERY_NAMESPACE,
            f"{channel_id}\0{cue_id}\0{page_index}",
        )
    )


@dataclass(frozen=True)
class CaptionFeedScanResult:
    """Outcome of one ``run_once`` scan."""

    channels: int = 0
    cues_sent: int = 0
    cues_dropped: int = 0  # send returned False (worker FIFO not ready / not gst engine)
    sent_channels: tuple[str, ...] = field(default_factory=tuple)


class CaptionFeedWorker:
    """Push each ON_AIR channel's new caption cues into its live caption appsrc."""

    def __init__(
        self,
        *,
        work_dir: Path,
        on_air_channels: OnAirChannelsProvider,
        caption_cue_provider: CaptionCueProvider,
        send_caption_cue: SendCaptionCue,
    ) -> None:
        self._work_dir = work_dir
        self._on_air_channels = on_air_channels
        self._caption_cue_provider = caption_cue_provider
        self._send_caption_cue = send_caption_cue
        # Per-channel set of already-pushed cue ids (so a re-scan never double-sends).
        self._sent: dict[str, set[str]] = {}
        # A multi-page cue can be only partly acknowledged. Retain each page's
        # acknowledgement independently so a retry never repeats pages already
        # accepted by the worker.
        self._acknowledged_pages: dict[str, set[tuple[str, int]]] = {}

    def run_forever(
        self, *, poll_seconds: float = 2.0, stop_event: threading.Event | None = None
    ) -> None:
        """Run the feed loop until ``stop_event`` is set; scan errors are logged."""
        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                _LOG.exception("Caption feed scan failed; continuing.")
            if stop_event is None:
                threading.Event().wait(poll_seconds)  # pragma: no cover - loop shape
            else:
                stop_event.wait(poll_seconds)

    def run_once(self) -> CaptionFeedScanResult:
        on_air = self._on_air_channels()
        # Forget channels that went off air so a later return re-sends from scratch.
        self._sent = {cid: seen for cid, seen in self._sent.items() if cid in on_air}
        self._acknowledged_pages = {
            cid: seen for cid, seen in self._acknowledged_pages.items() if cid in on_air
        }
        sent = 0
        dropped = 0
        touched: list[str] = []
        for channel_id in on_air:
            seen = self._sent.setdefault(channel_id, set())
            acknowledged_pages = self._acknowledged_pages.setdefault(channel_id, set())
            channel_sent = False
            for cue in self._caption_cue_provider(channel_id):
                if cue.cue_id in seen:
                    continue
                pages = cea_caption_pages(cue.text)
                cue_duration = max(0.0, cue.end_seconds - cue.start_seconds)
                page_duration = cue_duration / len(pages)
                for index, page in enumerate(pages):
                    page_key = (cue.cue_id, index)
                    if page_key in acknowledged_pages:
                        continue
                    if self._send_caption_cue(
                        channel_id,
                        self._work_dir,
                        text=page,
                        pts_seconds=cue.start_seconds + (index * page_duration),
                        duration_seconds=page_duration,
                        delivery_id=caption_page_delivery_id(
                            channel_id,
                            cue.cue_id,
                            index,
                        ),
                    ):
                        acknowledged_pages.add(page_key)
                if all(
                    (cue.cue_id, index) in acknowledged_pages
                    for index in range(len(pages))
                ):
                    seen.add(cue.cue_id)  # only mark sent on a successful push
                    sent += 1
                    channel_sent = True
                else:
                    dropped += 1
            if channel_sent:
                touched.append(channel_id)
        return CaptionFeedScanResult(
            channels=len(on_air),
            cues_sent=sent,
            cues_dropped=dropped,
            sent_channels=tuple(touched),
        )


def build_caption_feed_worker(
    session_factory: SessionFactory,
    *,
    send_caption_cue: SendCaptionCue,
    work_dir: Path | None = None,
    caption_sidecar_for: Callable[[str], Path] | None = None,
) -> CaptionFeedWorker:
    """Wire the production caption feed worker.

    ``on_air_channels`` reads channel state; ``caption_cue_provider`` loads the channel's
    active caption cues from its sidecar (``<work_dir>/<channel>/captions/active.vtt`` by
    default — the same file the decode-back proof reads); ``send_caption_cue`` is the gst
    strategy's FIFO command (a no-op drop on the ffmpeg engine). The sidecar's production
    by the captions pipeline + the live PTS alignment are WSL/LPM-validated."""
    from civiccast.egress.automation import default_egress_work_dir
    from civiccast.egress.store import PostgresEgressStore

    store = PostgresEgressStore(session_factory)
    resolved_work_dir = (work_dir or default_egress_work_dir()).expanduser()

    def _on_air() -> list[str]:
        channels: list[str] = []
        for config in store.list_configs():
            state_row = store.read_state(config.channel_id)
            if state_row is not None and state_row.state == "ON_AIR":
                channels.append(config.channel_id)
        return channels

    def _cues(channel_id: str) -> list[CaptionCue]:
        sidecar = (
            caption_sidecar_for(channel_id)
            if caption_sidecar_for is not None
            else resolved_work_dir / channel_id / "captions" / "active.vtt"
        )
        if sidecar.exists():
            return load_caption_cues_from_timed_text(sidecar, source_id=channel_id)
        return []

    return CaptionFeedWorker(
        work_dir=resolved_work_dir,
        on_air_channels=_on_air,
        caption_cue_provider=_cues,
        send_caption_cue=send_caption_cue,
    )
