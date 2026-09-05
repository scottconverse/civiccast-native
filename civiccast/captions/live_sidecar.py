# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Atomic live WebVTT publication for caption feed and decode-back workers."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from civiccast.captions.models import CaptionCue
from civiccast.captions.webvtt import render_webvtt


class LiveWebVttPublisher:
    """Publish one channel's complete stable cue set without partial readers."""

    def __init__(self, active_path: Path) -> None:
        self.active_path = active_path.expanduser().resolve()

    def reset(self) -> None:
        """Remove stale cues at worker startup while keeping a valid WebVTT file."""

        self.publish([])

    def publish(self, cues: list[CaptionCue]) -> None:
        """Atomically replace ``active.vtt`` with the complete stable cue set."""

        _atomic_write_text(self.active_path, render_webvtt(cues))


def active_caption_sidecar(work_dir: Path, channel_id: str) -> Path:
    """Return the shared producer/feed/proof path for one channel."""

    return work_dir / channel_id / "captions" / "active.vtt"


def caption_runtime_status_path(work_dir: Path, channel_id: str) -> Path:
    """Return the operator/support status path for one live-caption channel."""

    return work_dir / channel_id / "captions" / "runtime-status.json"


def publish_caption_runtime_status(
    work_dir: Path,
    channel_id: str,
    *,
    state: Literal["within-capacity", "overloaded", "storage-refused", "paused", "disabled"],
    backlog_segments: int,
    max_backlog_segments: int,
    refusal_reason: str | None = None,
    resume_in_seconds: float | None = None,
    consecutive_overloads: int | None = None,
) -> Path:
    """Atomically publish capacity state without implying decode-back readiness.

    ``paused`` is the caption tap's backoff state
    (:mod:`civiccast.captions.tap_backoff`): this channel overloaded, its ASR
    is suspended for ``resume_in_seconds``, and live captions are off for that
    window so playout keeps the CPU. It carries ``resume_in_seconds`` and
    ``consecutive_overloads`` so the operator sees BOTH that captions stopped
    and when they will be attempted again -- an ``overloaded`` snapshot alone
    never said whether anything would happen next.
    """

    path = caption_runtime_status_path(work_dir, channel_id)
    if state in {"storage-refused", "disabled"}:
        LiveWebVttPublisher(active_caption_sidecar(work_dir, channel_id)).reset()
    payload: dict[str, object] = {
        "backlog_segments": backlog_segments,
        "channel_id": channel_id,
        "max_backlog_segments": max_backlog_segments,
        "state": state,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if refusal_reason is not None:
        payload["refusal_reason"] = refusal_reason
    if resume_in_seconds is not None:
        payload["resume_in_seconds"] = round(float(resume_in_seconds), 1)
    if consecutive_overloads is not None:
        payload["consecutive_overloads"] = int(consecutive_overloads)
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def reset_existing_live_sidecars(work_dir: Path) -> None:
    """Fail closed after restart by replacing every prior active sidecar with empty VTT."""

    root = work_dir.expanduser()
    if not root.is_dir():
        return
    for path in root.glob("*/captions/active.vtt"):
        if path.is_file():
            LiveWebVttPublisher(path).reset()


def _atomic_write_text(destination: Path, content: str) -> None:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


__all__ = [
    "LiveWebVttPublisher",
    "active_caption_sidecar",
    "caption_runtime_status_path",
    "publish_caption_runtime_status",
    "reset_existing_live_sidecars",
]
