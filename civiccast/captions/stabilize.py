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
    #: LIVE confirmation mode.  The live caption tap feeds overlapping audio
    #: windows (5 s segments with 4 s of overlap -- 9 s windows advancing 5 s),
    #: so it re-hears the same audio rather than re-transcribing one region
    #: twice.  In that flow two different windows over continuous speech rarely
    #: produce IDENTICAL text, so exact-text re-confirmation is unreachable and
    #: every cue expires unconfirmed (measured on Blackwell 2026-09-16 with
    #: device=cuda/float16: good ASR text, yet active.vtt stayed empty and the
    #: emitted stream carried only A/53 null padding).
    #:
    #: In live mode a later hypothesis that STARTS INSIDE the pending cue's own
    #: span has re-heard that same audio, and confirms the cue even when the
    #: wording changed.  The safety properties are preserved: a new reading at
    #: the SAME start is a correction and still resets the count, and a lone
    #: window is never committed without that corroboration.  Non-live callers
    #: (offline/VOD and every existing test) keep exact-text re-confirmation
    #: unchanged.
    live: bool = False
    #: Minimum fraction of the SHORTER window that must be shared for a later
    #: live window to count as a re-hearing.  The measured tap geometry (9 s
    #: windows advancing 5 s) shares 4/9 ~= 0.444, so the default sits just
    #: below that: real re-hearings pass, while a millisecond sliver of overlap
    #: (which previously confirmed an unrelated multi-second caption) does not.
    #: This is deliberately looser than the 0.5 revision floor used for
    #: offline/VOD text revisions; the two answer different questions.
    live_overlap_fraction: float = 0.4
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
        if not 0 < self.live_overlap_fraction <= 1:
            raise ValueError("live_overlap_fraction must be greater than 0 and at most 1")

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

        if self.live:
            # LIVE corroboration: a later window that begins inside a pending
            # cue's own span re-heard that same audio, so it confirms the cue
            # even when the wording changed.  A new reading at the SAME start is
            # a correction (checked first, below) and must keep resetting.
            for pending in self._pending:
                if self._reheard_enough_of(pending, hypothesis):
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

    def _reheard_enough_of(self, pending: _PendingCue, hypothesis: CaptionHypothesis) -> bool:
        """Has ``hypothesis`` genuinely re-heard enough of ``pending``'s audio?

        The live tap re-hears overlapping audio, so a later window that shares a
        SUBSTANTIAL part of the pending window is corroboration even when ASR
        re-words it.  The earlier guard only checked that the incoming start fell
        somewhere before ``pending.hypothesis.end_seconds`` -- the span ASR
        CLAIMED -- so a window beginning one millisecond (or one microsecond)
        inside an 8 s claim counted as corroboration and could air a completely
        different, otherwise uncorroborated caption.  Require the shared rule
        (at least half of the shorter window) instead of mere adjacency, and
        also require the re-heard region to be a real interval.
        """

        if hypothesis.start_seconds <= pending.hypothesis.start_seconds:
            # Same-or-earlier start is a correction / out of order, never a
            # later re-hearing of this pending cue.
            return False
        # The live tap advances by a full segment per window, so a genuine
        # re-hearing shares at least (window - advance) seconds of audio -- on
        # the measured Blackwell geometry, 9 s windows advancing 5 s share 4 s
        # (4/9 of the shorter window).  Require a fraction of the shorter window
        # that the real geometry clears comfortably, but a millisecond sliver
        # does not.  The shared _substantially_overlaps rule uses 0.5, which the
        # genuine 4/9 case FAILS, so live re-hearing needs its own lower floor
        # derived from that geometry rather than the stricter revision floor.
        shorter = min(
            pending.hypothesis.end_seconds - pending.hypothesis.start_seconds,
            hypothesis.end_seconds - hypothesis.start_seconds,
        )
        if shorter <= 0:
            return False
        return (
            _overlap_seconds(pending.hypothesis, hypothesis) / shorter >= self.live_overlap_fraction
        )

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
