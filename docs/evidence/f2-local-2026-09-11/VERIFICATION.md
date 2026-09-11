# F2 local release repair - 2026-09-11

Working branch: `fix/f2-release-readiness-20260911`, based on
`b2593a50b96c1696496461e2382ec6c396c9e940`. Local changes are not pushed.
Main remains d77b634e; PR219 remote source is 8653b56f. No new kit is accepted.

## Implemented locally

- Source preparation runs off the shared automation thread. The owner loop
  consumes completion after queued commands, so Stop cancels before late launch.
- Native preparation cancellation reaches loudness, conform and copy FFmpeg
  processes. Duration probing retains its existing 30-second bound. Prepared
  directory protection is supplied as an immutable snapshot.
- Reload pipe receipts mean accepted, sent before GLib arm work. Repeated IDs
  are acknowledged without reapplying. Commit/abort remains a separate receipt.
- Scheduled GStreamer plans contain one programme. Boundary-aware lookahead
  prepares the next programme within 120 seconds of the outgoing end. Only the
  existing applied receipt updates the current programme label. Non-GStreamer
  plans retain their existing behavior.
- Retired input-selector tail pads receive FLUSH_START before NULL teardown,
  releasing blocked streaming tasks before the new programme's held buffers
  are released. No FLUSH_STOP reopens the retired leg.
- Caption FAIL is visible with its blocker, sample time and next action. Checks
  refresh every 30 seconds; readings older than 2 minutes are marked stale.

## Executed evidence

- Root Python 3.12 baseline regression: blocked preparation prevents the next
  channel provider call (expected failure on unchanged b2593a50).
- Root integrated affected modules: 450 passed, 6 existing POSIX-only skips,
  12.73 seconds. Includes daemon, automation, source preparation, FFmpeg,
  loudness, worker acknowledgements and strategy tests.
- Root boundary integration after one-item scheduling: 274 passed, 7.44 seconds.
  Includes explicit future :25/:50/:55 item selection and label change only
  after settlement; 5-minute and hour-long items preload within bounded lead.
- Root native GStreamer run: 6 passed, 1 failed, 19 deselected, 89.37 seconds.
  The three-channel repeated rollover test failed on channel 2, second commit.
  Stack pins `_null_retiring_element` at `element.set_state(NULL)`. The old leg
  did not retire before the 15-second watchdog. This was a real failure found
  during integration; `retirement-failure-worker.log` preserves it.
- After the retirement fix, the exact native reproducer passed: 1 passed,
  25 deselected, 67.86 seconds. Three workers each completed six rollovers;
  all 18 commits passed the preroll log grader with 77 elements. The three
  `retirement-fixed-channel-*.log` files preserve those results.
- All seven affected native checks then passed together: 7 passed,
  19 deselected, 101.78 seconds. These cover immediate A/V, live UDP replacement,
  deferred boundaries, missing-preroll recovery, held-reload supersession and
  repeated three-worker retirement. This is native source execution, not an
  installed candidate soak. The old kit supplied runtime dependencies only.
- Final affected Python suite: 2265 passed, 72 skipped, 348.38 seconds.
  Skips cover unavailable integration runtimes/databases and platform-specific
  cases. The seven native cases above were run separately with the bundled
  runtime enabled. Python 3.12 was used for root integration.
- Operator UI: 1035 tests passed across 90 files. Lint and production build
  passed. Accessibility and contrast checks: 18 passed, Chromium desktop/mobile
  light/dark. This mocked preview does not prove an installed station UI.
- Mypy: 675 source files passed. Ruff check passed; source formatter check
  passed on 1531 files. OpenAPI generated-artifact check passed.

JUnit receipts and operator output are archived in `local-check-receipts.zip`.

## Evidence limits and next work

The archived sampler compares API labels, not active internal playlist segment
identity. Source inspection proves the old label stayed at segment 1 throughout
multi-item playlists. The one-item correction repairs that mechanism; it does
not retroactively prove why every historical :25/:50/:55 dispatch was absent.

The observed native retirement hang and caption display repair are locally
verified. Next is one consolidated existing-PR update, required CI, then a new
candidate build, Sandbox, Gate A and at least two hours on the selected tester.
No informational mutation wait is on this release critical path. The old
795cdab5 kit is still blocked and must not be published.

Known candidate checks: publish the complete intended schedule horizon before
soak; verify actual programme/label transitions and Stop; run captions ON/OFF.
The underlying zero-expected-caption-cue symptom is not claimed fixed by the
display change. Nonfatal reload-abort UI visibility, memory growth and dropped
frame metrics remain bounded observations for the soak, not new workstreams.
Owner for these release observations: CivicCast release coordinator, 2026-09-11.

OpenAI-only roles: root owns integration; Luna supplied channel-isolation and
boundary regressions (root corrected pass synchronization and command-id
assertion); Sol implemented cancellation and boundary provider; Terra implemented
early pipe acceptance and independently reviewed preparation ownership. Worker
tests used Python 3.13; the root integration results above used Python 3.12.
Terra supplied the retirement repair and reviewed the caption UI; Sol reviewed
the retirement flush semantics. Root accepted the actual integrated diffs and
executed the native checks and final gates listed above.
