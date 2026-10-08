# Beta 11 live caption policy — 2026-10-05

Scott explicitly removed the live repeated-recognition requirement on October
5, 2026. This supersedes older live confirmation assertions and tests.

Live caption tap pipelines publish the first recognition. Neither lexical
agreement, two observations, positive word duration, nor a minimum confidence
is a prerequisite for airing recognized text. Low confidence remains visible
in the existing review metadata. Offline batch confirmation is unchanged.

The tap still supplies overlapping PCM windows for recognition context.
The formatter selects words from newly covered audio and removes previously
aired boundary words when their text and observed spans overlap. Missing or
entirely zero-duration word timings use coarse PCM bounds and suffix/prefix
deduplication. An advancing recognition does not need corroboration. Replayed
or older windows cannot publish again.

Whistle no longer falls back because captions did not commit. Empty speech,
applause, and overlap deduplication are not model failures. Bounded process
startup, request deadlines, crash handling, and sticky per-channel Whisper
fallback remain. Needle telemetry remains disabled.

Candidate: 1.0.0-beta.11.dev4. Local installed patch only; no release or
clean-installer claim. Preserve the installed U69 tap changes.

Validation: first-pass tests failed against the old policy, then passed after
the change. Independent review reproduced and prompted fixes for mixed
zero-duration words and repeated boundary words. The affected caption,
runtime-wiring, native payload, prewarm, and version suite passed 242 tests.

Live evaluation order: all three stations on Whistle for two hours, then all
three on Whisper with the same first-pass policy for two hours. Use the
existing emitted-output observer and resource limits. No injected failure
during either engine-only campaign. A fallback prevents claiming a Whistle-only
pass. Judge actual emitted captions, stream continuity, audio shedding,
resource use, and sample caption quality. Do not equate recognized text or
database review rows with captions delivered on air.

The old confirmation rule demonstrably withheld captions; that evidence does
not establish that it caused every historical failure or exhausted-capacity
issue. Runtime campaign results belong in the dated report and evidence
directory, not this policy document.
