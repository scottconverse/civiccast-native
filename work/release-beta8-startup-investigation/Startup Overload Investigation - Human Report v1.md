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
