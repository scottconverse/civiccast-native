# Beta.7 R15 four-hour posthoc verification

Verdict: **PASS for the candidate's four-hour captions-OFF physical product
gate.** The original R15 job receipt remains `FAIL` because its final collector
mistook normal log rotation for truncation. This verification does not rewrite
that historical receipt. It binds and grades the terminal logs that R15 had
already copied to its preserved `all-raw` snapshot during cleanup.

## Exact identity

- Candidate source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- Tester: `DESKTOP-VBMA6O5`
- Mission: `BETA7-3E117FF1-OFF4H-R15-4F9B22`
- Measured interval: `2026-09-14T11:19:16.6067771Z` through
  `2026-09-14T15:19:16.6067771Z`
- Original R15 evidence commit: `b1c03b6a`
- Original R15 evidence SHA-256:
  `ee2edeb12d701d460f607acf4a400a180698107f9dcf5948464945c685ceb6d1`
- Recovered terminal-log evidence commit:
  `b8f02b426a2fe64000f149e610cf1fbfc19251d5`
- Recovered terminal-log archive SHA-256:
  `a01288b8bc500206bdd96709ecff78a7bea57bdba5fcb82948decdfb95a97865`
- Recovery autorun receipt commit: `71dd9dac4230eef5ad933a37d3f290ebe480e366`

The recovery order asserted the exact host, candidate, mission, historical job
error, local run verdict, and original evidence hash. It then copied the
terminal snapshot without installing, starting, stopping, scheduling, reading
the staff token, or rerunning the soak. The tester remotely verified the two
published blobs.

## Re-derived product evidence

The state stream contains 1,440 samples for each of public, education, and
government, or 4,320 total. Every sample is `ON_AIR`, every `last_error` is
empty, and each channel keeps one PID for the entire four hours: public 8636,
education 23528, and government 21212. The final samples are after the planned
four-hour endpoint and all three channels remain live.

The R15 boundary grader reports 144 of 144 planned programme changes within 30
seconds: 48 of 48 on each channel. The health stream contains 480 of 480
`healthy` beta.7 samples. All 24 TSDuck probes pass across eight rounds per
channel, covering 445,882 packets with zero invalid syncs, zero transport
errors, and zero discontinuities.

The exact premeasurement stdout/stderr slice for each channel occurs once in
the recovered terminal worker log. Grading the suffix after that slice with
R15's own `Get-Beta7FailureGrades`, `Get-Beta7WorkerTopologyGrade`, and
`Test-Beta7PostCommitOutput` functions gives:

- F-1: PASS
- F-3: PASS
- Worker topology: PASS
- Worker or reload-timeout lines: 0
- Transaction-order errors: 0
- Output-stall lines: 0
- Public: 48 complete commits, all `elements=33`, with later output
- Education: 48 complete commits, all `elements=33`, with later output
- Government: 48 complete commits, all `elements=33`, with later output

The terminal control-plane snapshot proves the rollover. The older active
generation is now `control_plane-app.log.1`, ending at local time 05:18:57.705.
The new active file begins at 05:18:59.962 and covers the measured interval
through 09:19:24.070. Across the exact post-premeasurement interval there are
zero `WORKER_RESULT`, `reload-commit-timeout`, or output-stall markers. Older
generations contain historical failures and were excluded by timestamp and the
premeasurement checkpoint, as the live harness intended.

## Harness defect and disposition

CivicCast intentionally rotates `control_plane-app.log` at 10 MiB and retains
10 backups. R15 saved only the active file length, then assumed the same path
still named the same generation four hours later. The log rolled between the
premeasurement checkpoint and measured start. At final collection the new
active file was smaller than the old generation's offset, so R15 threw before
writing its official log grade.

The candidate did not fail. The evidence now covers the complete measured
window and the exact GStreamer transaction rules that beta.5 and beta.6
violated. The next required release gate is the separate eight-hour physical
soak with rotation-aware log collection.
