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
class _PendingWord:
    word: CaptionWord
    window: tuple[float, float]
    votes: set[tuple[float, float]]
    committed: bool = False


@dataclass
class CaptionStabilizer:
    """Commit caption cues only after repeated stable hypotheses."""

    window_seconds: float = 4.0
    stable_windows: int = 2
    low_confidence_threshold: float = 0.75
    #: LIVE confirmation mode.  The live caption tap feeds overlapping audio
    #: windows (5 s segments with 5 s of overlap -- 10 s windows advancing 5 s),
    #: so it re-hears the same audio rather than re-transcribing one region
    #: twice.  In that flow two different windows over continuous speech rarely
    #: produce IDENTICAL text, so exact-text re-confirmation is unreachable and
    #: every cue expires unconfirmed (measured on Blackwell 2026-09-16 with
    #: device=cuda/float16: good ASR text, yet active.vtt stayed empty and the
    #: emitted stream carried only A/53 null padding).
    #:
    #: Production live observations carry actual ASR word timestamps and PCM
    #: provenance. Only repeated lexical phrases with overlapping observed word
    #: spans stabilize; each distinct PCM window contributes at most one vote.
    #: Legacy observations without word metadata use suffix/prefix confirmation.
    #: Offline/VOD exact-text re-confirmation is unchanged.
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
    _live_words: list[_PendingWord] = field(default_factory=list, init=False)
    _last_word_window: tuple[float, float] | None = field(default=None, init=False)

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

        if self.live and hypothesis.words is not None:
            return self._observe_live_words(hypothesis)
        self._latest_observed_end_seconds = max(
            self._latest_observed_end_seconds,
            hypothesis.end_seconds,
        )
        self._expire_stale_pending()
        if self.live:
            return self._observe_live(hypothesis)
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

    def _observe_live_words(self, hypothesis: CaptionHypothesis) -> list[CaptionCue]:
        """Align actual timed words from distinct, advancing PCM windows.

        No timing tolerance or interpolation: a match needs positive overlap
        between the model's observed word spans and a repeated lexical phrase.
        """
        start, end = hypothesis.audio_window_start_seconds, hypothesis.audio_window_end_seconds
        if start is None or end is None:
            pending = self._new_pending(hypothesis)
            self._pending.remove(pending)
            self._expired_unconfirmed.append(self._build_cue(pending, low_confidence=True))
            return []
        window = (start, end)
        if self._last_word_window is not None and window <= self._last_word_window:
            return []  # Same pass/replay/out-of-order observation is not a vote.
        self._last_word_window = window
        expired = [p for p in self._live_words if min(p.word.end_seconds, p.window[1]) <= start]
        self._review_words([p for p in expired if not p.committed], hypothesis)
        self._live_words = [
            p for p in self._live_words if min(p.word.end_seconds, p.window[1]) > start
        ]
        incoming = hypothesis.words or []
        if not incoming:
            pending = self._new_pending(hypothesis)
            self._pending.remove(pending)
            self._expired_unconfirmed.append(self._build_cue(pending, low_confidence=True))
            return []
        old = self._live_words

        def compatible(i: int, j: int) -> bool:
            previous, current = old[i], incoming[j]
            token = current.text.casefold().strip(punctuation + " ")
            return bool(token) and (
                token == previous.word.text.casefold().strip(punctuation + " ")
                and window not in previous.votes
                and min(previous.word.end_seconds, current.end_seconds, previous.window[1], end)
                > max(previous.word.start_seconds, current.start_seconds, previous.window[0], start)
            )

        # Monotonic one-to-one LCS constrained by real word-time overlap.
        table = [[0] * (len(incoming) + 1) for _ in range(len(old) + 1)]
        for i in range(len(old) - 1, -1, -1):
            for j in range(len(incoming) - 1, -1, -1):
                table[i][j] = (
                    1 + table[i + 1][j + 1]
                    if compatible(i, j)
                    else max(table[i + 1][j], table[i][j + 1])
                )
        pairs: list[tuple[int, int]] = []
        i = j = 0
        while i < len(old) and j < len(incoming):
            if compatible(i, j):
                pairs.append((i, j))
                i += 1
                j += 1
            elif table[i + 1][j] >= table[i][j + 1]:
                i += 1
            else:
                j += 1
        runs: list[list[tuple[int, int]]] = []
        for pair in pairs:
            if runs and pair == (runs[-1][-1][0] + 1, runs[-1][-1][1] + 1):
                runs[-1].append(pair)
            else:
                runs.append([pair])
        accepted = [
            pair for run in runs if len(run) >= 2 or len(incoming) == len(old) == 1 for pair in run
        ]
        matched: set[int] = set()
        confirmed: list[tuple[int, CaptionWord]] = []
        for i, j in accepted:
            previous, current = old[i], incoming[j]
            matched.add(j)
            common = current.model_copy(
                update={
                    "start_seconds": max(
                        previous.word.start_seconds,
                        current.start_seconds,
                        previous.window[0],
                        start,
                    ),
                    "end_seconds": min(
                        previous.word.end_seconds, current.end_seconds, previous.window[1], end
                    ),
                    "confidence": min(
                        previous.word.confidence, current.confidence, hypothesis.confidence
                    ),
                }
            )
            previous.votes.add(window)
            previous.word = current.model_copy(update={"confidence": common.confidence})
            previous.window = window
            if not previous.committed and len(previous.votes) >= self.stable_windows:
                previous.committed = True
                confirmed.append((j, common))
        for j, word in enumerate(incoming):
            if j not in matched:
                observation = word.model_copy(
                    update={"confidence": min(word.confidence, hypothesis.confidence)}
                )
                old.append(_PendingWord(observation, window, {window}))
        old.sort(key=lambda p: (p.word.start_seconds, p.word.end_seconds))
        groups: list[list[tuple[int, CaptionWord]]] = []
        for item in confirmed:
            if groups and item[0] == groups[-1][-1][0] + 1:
                groups[-1].append(item)
            else:
                groups.append([item])
        if not groups:
            return []
        # One PCM-window update is one caption page, rather than a burst of
        # subsecond fragments. An editorial ellipsis exposes withheld interior
        # words: never silently join the two sides into a different sentence.
        words = [item[1] for group in groups for item in group]
        common_phrase = hypothesis.model_copy(
            update={
                "text": " ... ".join(
                    " ".join(item[1].text.strip() for item in group) for group in groups
                ),
                "start_seconds": min(w.start_seconds for w in words),
                "end_seconds": max(w.end_seconds for w in words),
                "confidence": min(w.confidence for w in words),
                "words": words,
            }
        )
        return [self._commit(self._new_pending(common_phrase, stable_count=self.stable_windows))]

    def _review_words(self, words: list[_PendingWord], hypothesis: CaptionHypothesis) -> None:
        if not words:
            return
        # Review-only coarse window bounds also accommodate model zero-duration
        # words without inventing a word duration or airing them.
        review = hypothesis.model_copy(
            update={
                "text": " ".join(p.word.text.strip() for p in words),
                "start_seconds": min(p.window[0] for p in words),
                "end_seconds": max(p.window[1] for p in words),
                "words": [p.word for p in words],
            }
        )
        pending = self._new_pending(review)
        self._pending.remove(pending)
        self._expired_unconfirmed.append(self._build_cue(pending, low_confidence=True))

    def _observe_live(self, hypothesis: CaptionHypothesis) -> list[CaptionCue]:
        """Confirm text, not an entire window merely sharing some audio.

        Segment timestamps bound a coarse shared interval. They do not provide
        word alignment: do not interpolate timestamps for either unmatched tail.
        Whole-text repeats permit single-word cues; partial matches require a
        phrase (two or more tokens), not a coincidental shared function word.
        """
        words = hypothesis.text.split()
        normalized = [word.casefold().strip(punctuation) for word in words]
        # A repeated full window may include text already committed from its
        # prefix. Strip that prefix before it can overwrite the pending tail.
        for cue in self.committed():
            emitted = [word.casefold().strip(punctuation) for word in cue.text.split()]
            if _substantially_overlaps(cue, hypothesis) and normalized[: len(emitted)] == emitted:
                words = words[len(emitted) :]
                normalized = normalized[len(emitted) :]
        if not words:
            return []
        hypothesis = hypothesis.model_copy(update={"text": " ".join(words)})
        for pending in list(self._pending):
            previous = pending.hypothesis
            old_words = previous.text.split()
            old_normalized = [word.casefold().strip(punctuation) for word in old_words]
            previous_window = (
                previous.audio_window_start_seconds,
                previous.audio_window_end_seconds,
            )
            incoming_window = (
                hypothesis.audio_window_start_seconds,
                hypothesis.audio_window_end_seconds,
            )
            if previous_window[0] is not None and incoming_window[0] is not None:
                if previous_window == incoming_window:
                    continue
                old_start, old_end = previous_window
                new_start, new_end = incoming_window
            else:
                old_start, old_end = previous.start_seconds, previous.end_seconds
                new_start, new_end = hypothesis.start_seconds, hypothesis.end_seconds
            assert (
                old_start is not None
                and old_end is not None
                and new_start is not None
                and new_end is not None
            )
            shorter = min(
                old_end - old_start,
                new_end - new_start,
            )
            shared = max(0, min(old_end, new_end) - max(old_start, new_start))
            if shared / shorter < self.live_overlap_fraction:
                continue
            common_start = max(
                previous.start_seconds, hypothesis.start_seconds, old_start, new_start
            )
            common_end = min(previous.end_seconds, hypothesis.end_seconds, old_end, new_end)
            if common_end <= common_start:
                continue
            count = 0
            if old_normalized == normalized and all(normalized):
                count = len(words)
            elif hypothesis.start_seconds > previous.start_seconds:
                for size in range(min(len(words), len(old_words)), 1, -1):
                    if all(normalized[:size]) and old_normalized[-size:] == normalized[:size]:
                        count = size
                        break
            if not count:
                continue

            self._pending.remove(pending)
            if len(old_words) > count:
                # The earlier unique prefix was heard only once. Make its loss
                # visible in the existing review path, never the on-air track.
                prefix = previous.model_copy(update={"text": " ".join(old_words[:-count])})
                dropped = self._new_pending(prefix)
                self._pending.remove(dropped)
                self._expired_unconfirmed.append(self._build_cue(dropped, low_confidence=True))
            common = previous.model_copy(
                update={
                    "text": " ".join(old_words[-count:]),
                    "start_seconds": common_start,
                    "end_seconds": common_end,
                    "confidence": min(previous.confidence, hypothesis.confidence),
                    "audio_window_start_seconds": hypothesis.audio_window_start_seconds,
                    "audio_window_end_seconds": hypothesis.audio_window_end_seconds,
                }
            )
            confirmed = self._new_pending(common, stable_count=pending.stable_count + 1)
            if len(words) > count:
                self._new_pending(hypothesis.model_copy(update={"text": " ".join(words[count:])}))
            if confirmed.stable_count >= self.stable_windows:
                return [self._commit(confirmed)]
            return []

        # A revised reading of the same segment resets, rather than corroborates.
        for pending in self._pending:
            if (
                pending.hypothesis.start_seconds == hypothesis.start_seconds
                and _substantially_overlaps(pending.hypothesis, hypothesis)
            ):
                pending.hypothesis = hypothesis
                pending.stable_count = 1
                return []
        pending = self._new_pending(hypothesis)
        if self.stable_windows == 1:
            return [self._commit(pending)]
        return []

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
        """Finish pending observations at end of stream.

        Timed live words lacking confirmation become review-only observations,
        never active cues. Legacy/offline pending cues retain their historical
        low-confidence commit behavior described below.

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

        if self._live_words:
            first = self._live_words[0]
            review_context = CaptionHypothesis(
                source_id="timed-word-flush",
                start_seconds=first.window[0],
                end_seconds=first.window[1],
                text="pending timed words",
            )
            self._review_words([p for p in self._live_words if not p.committed], review_context)
            self._live_words.clear()
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
