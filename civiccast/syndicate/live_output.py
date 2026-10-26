# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""An app-owned YouTube reach output, isolated from local channel playout."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from civiccast.platform.worker_runtime import ThreadSupervisor
from civiccast.stream._ffmpeg import FfmpegProcessHandle, start_ffmpeg
from civiccast.syndicate.models import YouTubePublishProof

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from civiccast.syndicate.youtube import YouTubeClient


@dataclass
class _Delivery:
    client: YouTubeClient = field(repr=False)
    proof: YouTubePublishProof
    broadcast_id: str
    stream_id: str
    process: FfmpegProcessHandle | None = field(default=None, repr=False)
    started: float = field(default_factory=time.monotonic)


class YouTubeLiveOutput:
    """Send a selected channel's existing HLS output, and confirm at destination."""

    def __init__(
        self,
        source_for_channel: Callable[[str], Path],
        record_status: Callable[[str, YouTubePublishProof], None],
        *,
        launch: Callable[..., FfmpegProcessHandle] = start_ffmpeg,
        start_timeout_seconds: float = 120.0,
    ) -> None:
        self._source = source_for_channel
        self._record_status = record_status
        self._launch = launch
        self._timeout = start_timeout_seconds
        self._deliveries: dict[str, _Delivery] = {}
        self._lock = threading.RLock()
        self._supervisor = ThreadSupervisor(
            name="youtube-live-output",
            run_forever=self.run_forever,
            # Two Data API status reads per poll: 30 s keeps one continuous
            # output below the usual 10,000-unit daily quota. UI refresh is local.
            poll_seconds=30.0,
            enabled=True,
        )

    def start(
        self, client: YouTubeClient, *, asset_id: str, title: str, channel_id: str
    ) -> YouTubePublishProof:
        with self._lock:
            previous = self._deliveries.get(asset_id)
            if previous and previous.proof.delivery_state in {"configured", "starting", "live"}:
                if previous.proof.channel_id != channel_id:
                    raise ValueError("Stop this YouTube output before choosing another channel.")
                return previous.proof.model_copy()
            source = self._source(channel_id)
            broadcast_id, stream_id, ingest = client.configure_live(title=title)
            delivery = _Delivery(
                client=client,
                broadcast_id=broadcast_id,
                stream_id=stream_id,
                proof=YouTubePublishProof(
                    target_type="youtube_live",
                    url=f"https://www.youtube.com/watch?v={broadcast_id}",
                    credential_key="civiccast-provider://youtube",
                    delivery_state="configured",
                    channel_id=channel_id,
                ),
            )
            self._deliveries[asset_id] = delivery
            try:
                # Existing FFmpeg owner supplies hidden launch + kill-on-close containment.
                # Do not capture raw stderr: it can contain the private ingest URL/key.
                delivery.process = self._launch(
                    [
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-re",
                        "-i",
                        str(source),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0",
                        "-c",
                        "copy",
                        "-f",
                        "flv",
                        ingest,
                    ]
                )
                self._state(delivery, "starting")
            except Exception:
                self._state(delivery, "failed")
                self._finish_destination(delivery)
            self._supervisor.start()
            return delivery.proof.model_copy()

    @staticmethod
    def _state(delivery: _Delivery, state: str) -> None:
        delivery.proof = delivery.proof.model_copy(
            update={
                "delivery_state": state,
                "confirmed_live": delivery.proof.confirmed_live or state == "live",
            }
        )

    @staticmethod
    def _finish_destination(delivery: _Delivery) -> bool:
        try:
            delivery.client.finish_live(delivery.broadcast_id, delivery.stream_id)
        except Exception:
            return False
        return True

    def _persist(self, asset_id: str, delivery: _Delivery) -> None:
        self._record_status(asset_id, delivery.proof.model_copy())

    def run_once(self) -> None:
        with self._lock:
            for asset_id, delivery in self._deliveries.items():
                if delivery.proof.delivery_state not in {"starting", "live"}:
                    self._persist(asset_id, delivery)
                    continue
                try:
                    if delivery.process is None or delivery.process.poll() is not None:
                        raise RuntimeError("YouTube output exited.")
                    stream, broadcast = delivery.client.live_status(
                        delivery.broadcast_id, delivery.stream_id
                    )
                    if stream == "active" and broadcast == "live":
                        self._state(delivery, "live")
                    elif delivery.proof.delivery_state == "live" or broadcast in {
                        "complete",
                        "revoked",
                    }:
                        raise RuntimeError("YouTube destination stopped receiving this output.")
                    elif time.monotonic() - delivery.started > self._timeout:
                        raise RuntimeError(
                            "YouTube did not confirm delivery before startup timed out."
                        )
                except Exception:
                    if delivery.process is not None:
                        delivery.process.terminate()
                    self._state(delivery, "failed")
                    self._finish_destination(delivery)
                try:
                    self._persist(asset_id, delivery)
                except Exception:
                    _LOG.warning(
                        "YouTube output status could not be saved; retrying on the next poll."
                    )

    def knows(self, asset_id: str) -> bool:
        with self._lock:
            return asset_id in self._deliveries

    def stop(self, asset_id: str) -> YouTubePublishProof:
        with self._lock:
            delivery = self._deliveries[asset_id]
            if delivery.process is not None:
                delivery.process.terminate()
            self._state(delivery, "stopped" if self._finish_destination(delivery) else "failed")
            self._persist(asset_id, delivery)
            return delivery.proof.model_copy()

    def run_forever(self, *, poll_seconds: float, stop_event: threading.Event) -> None:
        while not stop_event.wait(poll_seconds):
            try:
                self.run_once()
            except Exception:
                _LOG.warning("YouTube output status could not be saved; retrying on the next poll.")

    def close(self) -> None:
        self._supervisor.stop(timeout=35.0)
        for asset_id, delivery in list(self._deliveries.items()):
            if delivery.proof.delivery_state in {"configured", "starting", "live"}:
                try:
                    self.stop(asset_id)
                except Exception:
                    _LOG.warning("YouTube output stopped but final status could not be saved.")
