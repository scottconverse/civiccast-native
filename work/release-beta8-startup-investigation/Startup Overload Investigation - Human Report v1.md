# Startup Overload Investigation - Human Report v1

September 17, 2026, Mountain Daylight Time. Source inspected: 904a8453.

## Bottom line

The old startup caption pauses are still unexplained. Two later successful
starts do not prove they were fixed. We are not treating the old coder report's
"NO RELEASE BLOCKER" statement as permission to release.

## What the code and probes establish

The automation and caption workers start on independent threads. A genuine
channel Start clears that channel's old audio chunks before starting its new
writer. That does not prevent new audio from arriving while the caption worker
is busy. The first retention check runs synchronously before the backlog check;
later retention checks run in the background. Model loading happens after the
current backlog check, so a slow cold load can affect the following scan.

Three diagnostic probes passed: holding the initial retention check with two
fresh complete chunks lets both be consumed; three chunks trip the unchanged
backlog limit without transcription. Holding model preparation while three more
chunks arrive lets the first snapshot finish, then trips the following scan.

Command:
`.venv\Scripts\python.exe -m pytest work/release-beta8-startup-investigation/test_startup_probe.py -q -p no:cacheprovider`

Observed result: `3 passed in 1.02s`.

These are controlled scheduling probes with fake runtime/retention and atomic
complete files. They are NOT a real-time five-second audio stream, GPU test,
installed acceptance, or proof of which mechanism caused the historical pause.
Default non-atomic scanning excludes the newest chunk; the historical host's
mode and phase timing must not be inferred from these atomic probes.

## What remains unknown

The preserved report measures 13-14 seconds from tap-thread startup, not from
writer startup or retention entry. A measured 4-5-second sweep alone does not
explain three new five-second chunks starting from an empty directory. Earlier
arrivals, retained chunks, cold loading, slower startup phases, or combinations
remain possible. The stronger old checkpoint attribution is not independently
supported by a contemporaneous phase trace.

## Next discriminating check

On an unchanged-configuration cold startup, preserve monotonic phase timing,
channel/session identity, retention entry/exit/verdict, reset completion and
chunk inventory, writer start/arrivals, backlog snapshots, model preparation,
and first transcription. Keep the existing GPU workload and policy thresholds.
Use that evidence to choose the repair, not a guessed root cause.

No service, installed code, credentials, schedule, or policy was changed by
this investigation. Authenticated operator access is still needed for a safe
live run. Release readiness and long-run reliability remain unproved.

## Diagnostic preparation at 12:44 p.m. MDT

The existing observer cannot time individual retention/model-loading phases.
Its HTTP/GPU sampling loop may take longer than its nominal interval, so gaps
between samples are not proof of the time spent in one internal operation.
An independently reviewed implementation plan therefore calls for opt-in,
bounded monotonic phase receipts in the tap process. That implementation is
in progress, not installed or accepted yet. It must not change caption policy.

New local utility `watch_tap_metadata.py` records complete polling inventories
of selected channels' chunk filenames, sizes and modification times. It does
not read audio or write to the tap root. Receipts go to a new, exclusive file
outside that root. Missing directories are explicit errors, not empty success.
Polling can miss short-lived files; these are observation times, NOT exact
writer create/rename/delete timestamps. The internal backlog receipt remains
the authority for what the caption worker actually counted.

Command (actual tap root/channel IDs must first come from station inventory):
`python watch_tap_metadata.py --tap-root ACTUAL_ROOT --channels ACTUAL_IDS --output NEW_RECEIPT.jsonl --seconds 240 --interval 0.25`

Fixture check:
`.venv\Scripts\python.exe -m pytest work/release-beta8-startup-investigation/test_watch_tap_metadata.py -q -p no:cacheprovider`
returned `8 passed in 0.29s`. Initial collection failed because the standalone
work-directory module was not on the import path; its test now loads the exact
sibling module explicitly. That collection error is not a behavioral RED test.
Independent review found a real directory-junction boundary issue: a selected
channel could point outside the requested tap root. The watcher now checks the
resolved boundary before every scan and after enumeration, discarding an
escaped inventory. The expanded fixture check returned `10 passed in 0.30s`;
independent recheck passed 10 fixtures in 0.31s and a real Windows junction
negative test. This is not OS-level security isolation against
an attacker changing junctions during the scan. No live watcher has started.

Opt-in logging itself can perturb timing. Phase timestamps should be captured
before logging, and event/time limits may truncate phase pairs. A missing end
record alone is not evidence of a stalled operation. Reports must disclose
those limits and compare against ordinary configuration, not manufacture a
causal conclusion from the diagnostic run alone.
