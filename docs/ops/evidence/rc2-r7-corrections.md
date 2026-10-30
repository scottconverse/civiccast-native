# R7 findings carried into RC2 — October 30, 2026

R7's complete saved reports, proof logs, screenshots and monitoring data were
reviewed read-only from `D:/RC1 Test Results`. Existing R9 corrections are
retained. RC1 and the running stations/soaks were not modified.

## Corrected boundaries

- Restricted service identity: Modify is granted only to installed Ollama model
  data (including the legacy data location); executable/runtime roots retain RX.
  Existing Windows identity tests, including real temporary-file ACL checks: 16 passed.
- Both scheduling drawers accept minutes plus seconds. Their focused tests
  submit a 38-second clip. Publication remains separate from scheduling.
- Watch-folder failures remain visible beside the form, including actionable
  service-account access guidance. Focused screen suite: 19 passed.
- Minutes refusal displays the server's explanation and links to caption review;
  the approval prerequisite remains enforced. Sample, Live Room and minutes UI
  checks: 35 passed; Commit-to-Air screen checks: 15 passed.
- The bundled sample is a file/private rehearsal, not a fake network camera.
  Creating it no longer registers a dead RTMP source. The unchanged private
  placeholder from older installs is excluded from Live Room source choices;
  edited or genuine sources remain available.
- Resident guide includes manual and recurring published premieres, excludes
  drafts/withdrawn/embargoed items, and deduplicates recurring schedule IDs.
  Published/draft visibility API checks: 13 passed.
- As-run records resolve the planned start from the matching schedule item while
  retaining the separately observed actual start. Missing comparison metadata
  does not discard actual output evidence. Capture/close tests: 22 passed.
- GStreamer reports measured TS bitrate and encoded video cadence, including zero
  progress on a stalled interval. Health reads only the current worker's log
  span. Watchdog/measurement tests: 42 passed. The native caption run below also
  produced real `fps=30.00` and nonzero bitrate breadcrumbs on all three channels.
- Release downloads retain byte resume/hash checks and print byte progress every
  five seconds. Existing downloader/proof checks: 15 passed initially; four
  Windows PowerShell cases needed the Windows module directory restored in the
  isolated test child's PSModulePath, then all four passed. No application
  workaround or assertion relaxation was made for that environment failure.

TypeScript build/type checks and changed-file ESLint passed. Ruff passed on the
changed Python files; mypy passed the five changed integration modules. Manual
chapters and built-in Help were updated with these behaviors. Render completion,
required CI, signed candidate and focused installed repeat are tracked in CURRENT,
not inferred from this source-level record.

## Actual caption generation and transport

Receipts: `work/r7-caption-proof/tap-result.json` and
`work/r7-caption-proof/transport-isolated/report.json` in the RC2 worktree.
The source-bound compact receipt is `rc2-r7-caption-result.json` beside this file.

The production CaptionTapWorker used pinned Whistle assets and saved original
R9 speech WAVs. Five 5-second arrivals per channel, three channels, yielded all
15 segments consumed; zero overload discards, quarantines or expired cues;
Whistle primary on all channels; five nonempty cues per channel. Cold cycle:
5.047 seconds. Warm cycles: 2.579, 4.230, 3.356 and 4.787 seconds.

The existing native transport proof fed those actual cues through CaptionFeedWorker,
Win32 named pipes, production GStreamer workers, live appsrc/CEA-708 insertion,
emitted MPEG-TS and decode-back. All 15 cues were recovered on the three channels,
with zero pre-delivery drops and normal worker teardown. The reused native tree's
246-file manifest passed. Workers used process-specific proof pipe names.

The first transport invocation refused generated Python bytecode outside the
manifest. Only those 16 generated `.pyc` files in the contained owned candidate
were removed; bytecode writing was disabled for the proof. The next invocation
refused an existing default channel pipe without changing it. The proof script
was corrected to use unique isolated names before the successful execution.

Limits: this is a bounded development-host check on saved audio, not an installed
R7/R9 soak or a claim of transcript accuracy, translation review, caption uptime
over hours, or guaranteed capacity under arbitrary load. Queue depth alone is
not loss proof. The next tester should repeat the failed operator actions and
observe all three actual captioned outputs on the single delivered RC2 candidate.

## Existing decisions retained

Credential validation redaction and earlier R9 fixes retain their prior focused
evidence. R7 did not retest the credential leak. The historical owner-accepted RC1
audio PTS limitation remains accepted; it was not reopened. The named GLib
finding has a separate exact-version application-reachability assessment, not a
blanket scanner exemption or a new native-library rebuild.
