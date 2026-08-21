# 4-hour soak kit (v3.0)

This is the kit the tester directive references at:

`$Kit = "$DirectiveRepo\tester-handoff\v3.0\soak-4h"`

It ships the supporting files the directive's section 2-4 steps need:

```text
soak-4h/
|-- README.md
|-- channels.yaml
|-- synthetic-probes/
|   |-- paywall.sh
|   |-- recording.sh
|   `-- agenda.sh
`-- scripts/
    |-- start-encoders.ps1
    |-- verify-egress.ps1
    `-- heartbeat.ps1
```

## What this kit proves

The soak is designed to prove that CivicCast can run the three PEG channels
continuously, expose a working `/api/health` endpoint, keep synthetic operator
workflows healthy, and prove live UDP MPEG-TS egress on every channel.

## How the heartbeat loop works

Every 30 minutes (`heartbeat.ps1 -HeartbeatIndex N`):

1. Sample process RSS for `uvicorn`, `ffmpeg`, and `python`.
2. Probe `/api/health` for HTTP 200 and retain the response body.
3. Run `scripts/verify-egress.ps1`, which captures every UDP MPEG-TS sink with
   TSDuck and writes:
   `$RUN_ROOT\egress-verify\egress-verify-<UTC-stamp>.json`.
4. Run every `synthetic-probes/*.sh` script with Git Bash or WSL. Each script
   exits 0 on all-pass and non-zero on at least one finding. The heartbeat JSON
   records the exit code and the last 5 lines of output.
5. Atomically write a collision-resistant heartbeat JSON to
   `$RUN_ROOT\heartbeats\<UTC-stamp>-heartbeat-<index>-<unique-id>.json` and
   copy that exact artifact atomically to `tester-handoff/v3.0/heartbeats/`
   in the directive repo.
6. Commit only that repository artifact and push the current commit to
   `tester/v3.0-finish-line-4h-soak` with the canonical message:
   `test: soak heartbeat <UTC-stamp> <NONCE>`.
7. Verify the remote branch resolves to the pushed commit before reporting
   success. The success receipt names the remote branch, artifact path, and
   verified commit SHA. Git or verification failures terminate non-zero.

Publication also fails closed if local `HEAD` is not already synchronized
with the tester branch or if another path is staged. It disables local Git
hooks for the script-owned commit and then verifies that the commit contains
only the heartbeat artifact. These checks prevent unrelated local work from
riding with soak evidence.

8 heartbeats x 30 minutes = 4 hours of coverage.

## How the encoders are managed

`start-encoders.ps1` spawns 3 detached `ffmpeg` processes, one per channel.
Each encoder writes:

- A file capture for final `tsanalyze`:
  `$RUN_ROOT\captures\<channel>\<channel>.ts`
- A live UDP MPEG-TS egress stream:
  - Public: `udp://127.0.0.1:9001?pkt_size=1316`
  - Education: `udp://127.0.0.1:9002?pkt_size=1316`
  - Government: `udp://127.0.0.1:9003?pkt_size=1316`

The encoder state lands in `$RUN_ROOT\state\encoders.json` with PIDs, capture
paths, UDP ports, and UDP URLs so heartbeat and stop scripts can find them.

The encoders use synthetic `lavfi` sources (color bars + 1 kHz tone), so the
soak does not require a real station feed on the tester.

## Egress verification

`verify-egress.ps1` runs a bounded TSDuck capture for each UDP sink and writes
one machine-readable artifact per heartbeat. PASS requires:

- Invalid syncs = 0
- Transport errors = 0
- Continuity discontinuities = 0

If TSDuck is unavailable, the verifier records `not-run` instead of faking a
pass. That is a release blocker for the soak, not a green result.

## Final tsanalyze sweep

At the end of the 4-hour window, the directive runs `tsanalyze` against each
capture file. PASS criteria:

- Discontinuities = 0
- Transport-error-indicator (TEF) = 0

The `analyzer:` block at the bottom of `channels.yaml` carries the pass-on
thresholds the result-writing script reads.

## Probe scripts

All three probe scripts exit 0 when every check passes and non-zero when any
check fails. The check shape is `<label> -> <expected>` prefixed with `ok` or
`FAIL`. A single `FAIL` line on any probe records the offending probe in the
heartbeat JSON. The post-soak result aggregates all heartbeat findings into the
verdict.
