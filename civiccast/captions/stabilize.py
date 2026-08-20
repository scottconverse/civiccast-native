# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-caption stabilization."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor

from civiccast.captions.models import CaptionCue, CaptionHypothesis


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass
class _PendingCue:
    hypothesis: CaptionHypothesis
    bucket: int
    ordinal: int
    stable_count: int = 1


@dataclass
class CaptionStabilizer:
    """Commit caption cues only after repeated stable hypotheses."""

    window_seconds: float = 4.0
    stable_windows: int = 2
    low_confidence_threshold: float = 0.75
    _pending: list[_PendingCue] = field(default_factory=list, init=False)
    _committed: list[CaptionCue] = field(default_factory=list, init=False)
    _expired_unconfirmed: list[CaptionCue] = field(default_factory=list, init=False)
    _bucket_ordinals: dict[int, int] = field(default_factory=dict, init=False)
    _latest_observed_end_seconds: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")
        if self.stable_windows < 1:
            raise ValueError("stable_windows must be at least 1")
        if not 0 <= self.low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between 0 and 1")

    def observe(self, hypothesis: CaptionHypothesis) -> list[CaptionCue]:
        """Observe one runtime hypothesis and return newly committed cues."""

        self._latest_observed_end_seconds = max(
            self._latest_observed_end_seconds,
            hypothesis.end_seconds,
        )
        self._expire_stale_pending()
        bucket = self._bucket_for(hypothesis.start_seconds)
        if self._overlaps_committed(hypothesis):
            return []

        pending = self._matching_pending(hypothesis)
        if pending is not None:
            pending.stable_count += 1
            pending.hypothesis = hypothesis
            if pending.stable_count >= self.stable_windows:
                return [self._commit(pending)]
            return []

        revision = self._revision_candidate(hypothesis)
        if revision is not None:
            revision.hypothesis = hypothesis
            revision.stable_count = 1
            return []

        ordinal = self._bucket_ordinals.get(bucket, 0) + 1
        self._bucket_ordinals[bucket] = ordinal
        pending = _PendingCue(
            hypothesis=hypothesis,
            bucket=bucket,
            ordinal=ordinal,
        )
        self._pending.append(pending)
        if self.stable_windows == 1:
            return [self._commit(pending)]
        return []

    def committed(self) -> list[CaptionCue]:
        """Return committed cues in playback order."""

        return sorted(
            self._committed,
            key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id),
        )

    def flush(self) -> list[CaptionCue]:
        """Commit every remaining pending cue in playback order.

        Call this once the caller knows no more audio is coming (end of
        stream, channel stop) -- there is no second transcription pass after
        that point, so anything still pending would otherwise be lost
        forever. A cue committed this way is flagged ``low_confidence``
        unless it already earned full re-confirmation (met the confidence
        threshold with ``stable_count >= stable_windows``); in practice a
        cue only remains pending because it never earned that, so flushed
        cues are always routed to the existing low-confidence review policy.
        Safe to call repeatedly: once pending is empty, later calls return
        an empty list.
        """

        ordered = sorted(
            self._pending,
            key=lambda pending: (
                pending.hypothesis.start_seconds,
                pending.hypothesis.end_seconds,
                pending.bucket,
                pending.ordinal,
            ),
        )
        flushed: list[CaptionCue] = []
        for pending in ordered:
            earned_confirmation = (
                pending.stable_count >= self.stable_windows
                and pending.hypothesis.confidence >= self.low_confidence_threshold
            )
            flushed.append(self._commit(pending, low_confidence=not earned_confirmation))
        return flushed

    def expired_unconfirmed(self) -> list[CaptionCue]:
        """Return pending cues dropped by :meth:`_expire_stale_pending`, in expiry order.

        These never earned re-confirmation and were never committed -- they
        must never be treated as active/on-air -- but they are counted and
        returned here instead of being silently deleted, so a drop is always
        observable.
        """

        return list(self._expired_unconfirmed)

    @property
    def expired_unconfirmed_count(self) -> int:
        """Total number of pending cues expired without re-confirmation."""

        return len(self._expired_unconfirmed)

    def _bucket_for(self, start_seconds: float) -> int:
        return floor(start_seconds / self.window_seconds)

    def _matching_pending(self, hypothesis: CaptionHypothesis) -> _PendingCue | None:
        normalized = _normalize(hypothesis.text)
        matches = [
            pending
            for pending in self._pending
            if _normalize(pending.hypothesis.text) == normalized
            and abs(pending.hypothesis.start_seconds - hypothesis.start_seconds)
            <= self.window_seconds
        ]
        if not matches:
            return None
        return min(
            matches,
            key=lambda pending: abs(pending.hypothesis.start_seconds - hypothesis.start_seconds),
        )

    def _revision_candidate(self, hypothesis: CaptionHypothesis) -> _PendingCue | None:
        candidates = [
            pending
            for pending in self._pending
            if _substantially_overlaps(pending.hypothesis, hypothesis)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda pending: _overlap_seconds(pending.hypothesis, hypothesis),
        )

    def _overlaps_committed(self, hypothesis: CaptionHypothesis) -> bool:
        normalized = _normalize(hypothesis.text)
        return any(
            _substantially_overlaps(cue, hypothesis)
            or (
                _normalize(cue.text) == normalized
                and abs(cue.start_seconds - hypothesis.start_seconds) <= self.window_seconds
            )
            for cue in self._committed
        )

    def _expire_stale_pending(self) -> None:
        oldest_relevant_end = self._latest_observed_end_seconds - (2 * self.window_seconds)
        survivors: list[_PendingCue] = []
        for pending in self._pending:
            if pending.hypothesis.end_seconds >= oldest_relevant_end:
                survivors.append(pending)
            else:
                self._expired_unconfirmed.append(self._build_cue(pending, low_confidence=True))
        self._pending = survivors

    def _build_cue(self, pending: _PendingCue, *, low_confidence: bool | None = None) -> CaptionCue:
        cue_id = f"cue-{pending.bucket:06d}"
        if pending.ordinal > 1:
            cue_id = f"{cue_id}-{pending.ordinal:02d}"
        resolved_low_confidence = (
            pending.hypothesis.confidence < self.low_confidence_threshold
            if low_confidence is None
            else low_confidence
        )
        return CaptionCue(
            cue_id=cue_id,
            start_seconds=pending.hypothesis.start_seconds,
            end_seconds=pending.hypothesis.end_seconds,
            text=pending.hypothesis.text,
            confidence=pending.hypothesis.confidence,
            low_confidence=resolved_low_confidence,
        )

    def _commit(self, pending: _PendingCue, *, low_confidence: bool | None = None) -> CaptionCue:
        self._pending.remove(pending)
        cue = self._build_cue(pending, low_confidence=low_confidence)
        self._committed.append(cue)
        return cue


def _overlap_seconds(
    first: CaptionCue | CaptionHypothesis,
    second: CaptionHypothesis,
) -> float:
    return max(
        0.0,
        min(first.end_seconds, second.end_seconds) - max(first.start_seconds, second.start_seconds),
    )


def _substantially_overlaps(
    first: CaptionCue | CaptionHypothesis,
    second: CaptionHypothesis,
) -> bool:
    shorter = min(
        first.end_seconds - first.start_seconds,
        second.end_seconds - second.start_seconds,
    )
    return shorter > 0 and _overlap_seconds(first, second) / shorter >= 0.5
