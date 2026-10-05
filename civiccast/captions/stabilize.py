# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-caption stabilization."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from string import punctuation

from civiccast.captions.models import CaptionCue, CaptionHypothesis, CaptionWord


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
    """Publish live recognition immediately; stabilize offline observations."""

    window_seconds: float = 4.0
    stable_windows: int = 2
    low_confidence_threshold: float = 0.75
    # Live broadcasts publish a single recognition. Offline confirmation remains
    # available for batch processing; it never gates the live caption track.
    live: bool = False
    _pending: list[_PendingCue] = field(default_factory=list, init=False)
    _committed: list[CaptionCue] = field(default_factory=list, init=False)
    _expired_unconfirmed: list[CaptionCue] = field(default_factory=list, init=False)
    _bucket_ordinals: dict[int, int] = field(default_factory=dict, init=False)
    _latest_observed_end_seconds: float = field(default=0.0, init=False)
    _last_word_window: tuple[float, float] | None = field(default=None, init=False)
    _last_live_words: list[CaptionWord] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")
        if self.stable_windows < 1:
            raise ValueError("stable_windows must be at least 1")
        if not 0 <= self.low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between 0 and 1")

    def observe(self, hypothesis: CaptionHypothesis) -> list[CaptionCue]:
        """Observe one runtime hypothesis and return newly committed cues."""

        if self.live:
            return self._observe_live(hypothesis)
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

    def _observe_live(self, hypothesis: CaptionHypothesis) -> list[CaptionCue]:
        """Air the first reading and discard audio already covered by a window.

        Timed words select the new audio tail. Without usable word timing, a
        suffix/prefix match removes only text already aired; it is not a vote
        or a prerequisite for publication. Zero-duration words use coarse audio
        bounds instead of disappearing from the live track.
        """
        start = hypothesis.audio_window_start_seconds
        end = hypothesis.audio_window_end_seconds
        if start is None or end is None:
            start, end = hypothesis.start_seconds, hypothesis.end_seconds
        previous = self._last_word_window
        if previous is not None and end <= previous[1]:
            return []
        self._last_word_window = (start, end)
        if not hypothesis.text.strip():
            return []
        boundary = max(start, previous[1]) if previous is not None else start
        words = hypothesis.words or []
        timed = any(w.end_seconds > w.start_seconds for w in words)
        if timed:
            words = [
                w
                for w in words
                if (w.end_seconds > boundary or w.start_seconds == w.end_seconds == boundary)
                and w.start_seconds < end
                and w.text.strip()
            ]
            if previous is not None and self._last_live_words:
                old = self._last_live_words
                for count in range(min(len(words), len(old)), 0, -1):
                    if (
                        all(w.start_seconds < boundary for w in words[:count])
                        and [w.text.casefold().strip(punctuation + " ") for w in old[-count:]]
                        == [w.text.casefold().strip(punctuation + " ") for w in words[:count]]
                        and all(
                            min(a.end_seconds, b.end_seconds)
                            > max(a.start_seconds, b.start_seconds)
                            for a, b in zip(old[-count:], words[:count], strict=True)
                        )
                    ):
                        words = words[count:]
                        break
            if not words:
                return []
            text = " ".join(w.text.strip() for w in words)
            cue_start = max(boundary, min(w.start_seconds for w in words))
            cue_end = min(end, max(w.end_seconds for w in words))
            confidence = min(hypothesis.confidence, *(w.confidence for w in words))
        else:
            tokens = hypothesis.text.split()
            if previous is not None and start < previous[1] and self._committed:
                old = self._committed[-1].text.split()

                def norm(xs):
                    return [x.casefold().strip(punctuation) for x in xs]

                for count in range(min(len(tokens), len(old)), 0, -1):
                    if norm(old[-count:]) == norm(tokens[:count]):
                        tokens = tokens[count:]
                        break
            if not tokens:
                return []
            text = " ".join(tokens)
            cue_start = max(boundary, hypothesis.start_seconds)
            cue_end = min(end, hypothesis.end_seconds)
            confidence = hypothesis.confidence
        if cue_end <= cue_start:
            cue_start, cue_end = boundary, end
        if cue_end <= cue_start:
            return []
        ready = hypothesis.model_copy(
            update={
                "text": text,
                "start_seconds": cue_start,
                "end_seconds": cue_end,
                "confidence": confidence,
                "words": words,
            }
        )
        self._last_live_words = words if timed else []
        return [self._commit(self._new_pending(ready))]

    def _new_pending(self, hypothesis: CaptionHypothesis, *, stable_count: int = 1) -> _PendingCue:
        bucket = self._bucket_for(hypothesis.start_seconds)
        ordinal = self._bucket_ordinals.get(bucket, 0) + 1
        self._bucket_ordinals[bucket] = ordinal
        pending = _PendingCue(hypothesis, bucket, ordinal, stable_count)
        self._pending.append(pending)
        return pending

    def committed(self) -> list[CaptionCue]:
        """Return committed cues in playback order."""

        return sorted(
            self._committed,
            key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id),
        )

    def flush(self) -> list[CaptionCue]:
        """Flush offline pending cues; live observations already aired."""

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
