# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-ON_AIR caption decode-back proof loop (S11a).

The embed side (GStreamer-native ``cccombiner``/``h264ccinserter``) inserts CEA-708
SEI; THIS loop is what proves it actually survived to the *emitted* stream and flips
``caption_status`` to ``on``. Each scan, for every ON_AIR channel: capture a short
segment of the emitted stream, decode its embedded captions, compare to the channel's
expected caption cues, and persist an ``EgressCaptionProofSample`` (which
``build_caption_status_provider`` reads — fail-closed: a fresh PASS → ``on``, anything
else → ``not-verified``).

The loop logic, cue selection, and persistence are unit-tested here with fakes. The
two live edges — capturing the emitted broadcast stream and the binding to the channel
caption pipeline's cues — are WSL/LPM-validated (a real live udp/srt egress + a real
caption source). Follows the ``ThreadSupervisor`` ``run_forever``/``run_once`` shape.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text
from civiccast.egress.caption_proof import (
    CaptionMode,
    Clock,
    FfmpegRunner,
    sample_caption_decode_back,
)
from civiccast.egress.store import EgressStore
from civiccast.stream._ffmpeg import run_ffmpeg

_LOG = logging.getLogger(__name__)

OnAirChannelsProvider = Callable[[], list[str]]
SegmentCapture = Callable[[str], Path | None]
ExpectedCuesProvider = Callable[[str], list[CaptionCue]]


@dataclass(frozen=True)
class CaptionProofScanResult:
    """Outcome of one ``run_once`` scan."""

    scanned: int = 0
    passed: int = 0
    failed: int = 0
    skipped_no_capture: int = 0
    channels: tuple[str, ...] = field(default_factory=tuple)


class CaptionProofWorker:
    """Sample caption decode-back for ON_AIR channels and persist the proof.

    All collaborators are injected so the loop is unit-testable without GStreamer,
    ffmpeg, or a live stream:

    * ``on_air_channels`` — the channels currently ON_AIR (and embedding captions).
    * ``capture_segment`` — capture a short emitted-stream segment for a channel,
      or None if no segment is available (then the channel is skipped — fail-closed,
      ``caption_status`` stays not-verified until a real capture proves a PASS).
    * ``expected_cues_provider`` — the cues the channel is embedding (the channel
      caption pipeline: review queue / ASR tap / sidecar). Empty → the sample is a
      FAIL with ``NO_EXPECTED_CUES`` (we never fabricate a PASS).
    """

    def __init__(
        self,
        *,
        store: EgressStore,
        on_air_channels: OnAirChannelsProvider,
        capture_segment: SegmentCapture,
        expected_cues_provider: ExpectedCuesProvider,
        mode: CaptionMode = "cea-708",
        runner: FfmpegRunner = run_ffmpeg,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._on_air_channels = on_air_channels
        self._capture_segment = capture_segment
        self._expected_cues_provider = expected_cues_provider
        self._mode = mode
        self._runner = runner
        self._clock = clock

    def run_forever(
        self,
        *,
        poll_seconds: float = 30.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Run the scan loop until ``stop_event`` is set; scan errors are logged."""
        while stop_event is None or not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                _LOG.exception("Caption proof scan failed; continuing.")
            if stop_event is None:
                threading.Event().wait(poll_seconds)  # pragma: no cover - loop shape
            else:
                stop_event.wait(poll_seconds)

    def run_once(self) -> CaptionProofScanResult:
        """Sample every ON_AIR channel once and persist each proof sample."""
        passed = 0
        failed = 0
        skipped = 0
        sampled: list[str] = []
        for channel_id in self._on_air_channels():
            segment = self._capture_segment(channel_id)
            if segment is None:
                skipped += 1
                continue
            sample = sample_caption_decode_back(
                channel_id=channel_id,
                emitted_stream_path=segment,
                expected_cues=self._expected_cues_provider(channel_id),
                mode=self._mode,
                runner=self._runner,
                clock=self._clock,
            )
            self._store.append_caption_proof_sample(sample)
            sampled.append(channel_id)
            if sample.status == "PASS":
                passed += 1
            else:
                failed += 1
        return CaptionProofScanResult(
            scanned=passed + failed,
            passed=passed,
            failed=failed,
            skipped_no_capture=skipped,
            channels=tuple(sampled),
        )


# --- live wiring (WSL/LPM edge) ------------------------------------------------

# Sink schemes whose emitted stream is captured live by ffmpeg for decode-back.
_CAPTURE_SINK_SCHEMES = ("udp", "srt")


def _emitted_stream_target(store: EgressStore, channel_id: str) -> tuple[str, bool] | None:
    """``(uri, is_file)`` for the channel's emitted stream to decode back, or None.

    Prefers a file/local-ts sink (the written TS — read its tail); else a live
    udp/srt broadcast sink (captured by ffmpeg). rtmp/sdi are not TS-decode targets."""
    config = store.get_config(channel_id)
    if config is None:
        return None
    for sink in config.sinks:
        if sink.kind in ("file", "local-ts"):
            parsed = urlsplit(sink.uri)
            return (parsed.path if parsed.scheme == "file" else sink.uri, True)
    for sink in config.sinks:
        if urlsplit(sink.uri).scheme.lower() in _CAPTURE_SINK_SCHEMES:
            return (sink.uri, False)
    return None


def capture_emitted_segment(
    store: EgressStore,
    channel_id: str,
    *,
    work_dir: Path,
    capture_seconds: float = 6.0,
    runner: FfmpegRunner = run_ffmpeg,
) -> Path | None:
    """Capture a short, bounded segment of the channel's emitted stream (WSL/LPM edge).

    A live udp/srt sink is captured for ``capture_seconds``; a file/local-ts sink's
    LAST ``capture_seconds`` are copied (``-sseof``) so a 24/7 channel's growing file is
    never decoded whole. Returns the segment path, or None if there is nothing to
    capture / the capture produced no bytes (then the channel is skipped, fail-closed)."""
    target = _emitted_stream_target(store, channel_id)
    if target is None:
        return None
    uri, is_file = target
    out = work_dir / channel_id / "caption-proof" / "segment.ts"
    out.parent.mkdir(parents=True, exist_ok=True)
    seconds = f"{capture_seconds:g}"
    if is_file:
        if not Path(uri).exists():
            return None
        args = ["-y", "-hide_banner", "-nostats", "-sseof", f"-{seconds}", "-i", uri]
    else:
        args = ["-y", "-hide_banner", "-nostats", "-i", uri]
    args += ["-t", seconds, "-c", "copy", "-f", "mpegts", str(out)]
    result = runner(args)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return None
    return out


SessionFactory = Callable[[], AbstractContextManager[Session]]


def build_caption_proof_worker(
    session_factory: SessionFactory,
    *,
    work_dir: Path | None = None,
    capture_seconds: float = 6.0,
    mode: CaptionMode = "cea-708",
    caption_sidecar_for: Callable[[str], Path] | None = None,
    runner: FfmpegRunner = run_ffmpeg,
) -> CaptionProofWorker:
    """Wire the production caption proof worker (Postgres store + live providers).

    ``on_air_channels`` reads channel state; ``capture_segment`` taps the emitted
    stream (live edge); ``expected_cues_provider`` loads the channel's embedded cues
    from its caption sidecar (``<work_dir>/<channel>/captions/active.vtt`` by default,
    overridable via ``caption_sidecar_for``). Absent sidecar → no expected cues → the
    sample fails closed (caption_status stays not-verified). The capture + the sidecar's
    production by the captions pipeline are WSL/LPM-validated."""
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

    def _capture(channel_id: str) -> Path | None:
        return capture_emitted_segment(
            store,
            channel_id,
            work_dir=resolved_work_dir,
            capture_seconds=capture_seconds,
            runner=runner,
        )

    def _expected(channel_id: str) -> list[CaptionCue]:
        sidecar = (
            caption_sidecar_for(channel_id)
            if caption_sidecar_for is not None
            else resolved_work_dir / channel_id / "captions" / "active.vtt"
        )
        if sidecar.exists():
            return load_caption_cues_from_timed_text(sidecar, source_id=channel_id)
        return []

    return CaptionProofWorker(
        store=store,
        on_air_channels=_on_air,
        capture_segment=_capture,
        expected_cues_provider=_expected,
        mode=mode,
        runner=runner,
    )
