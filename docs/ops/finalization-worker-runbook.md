<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Finalization Worker Runbook

Operating the CivicCast recording-finalization worker: the service that turns
an ended live broadcast into a recorded, packaged VOD asset.

What it does: when an operator ends a broadcast
(`POST /api/staff/live/sessions/{id}/end-broadcast`), the session enters
`ending`. The worker scans for `ending` sessions, resolves the recording file
at `<recording-target>/<live_session_id>.mp4`, waits for the file to settle
(size unchanged across scans), finalizes it into an asset at state `recorded`,
and packages it to HLS. Job state is persisted in `live_finalization_jobs` and
readable through the staff status endpoints below.

## Start modes

The deployment mode is selected with `CIVICCAST_FINALIZATION_WORKER`:

| Mode | Behavior | When to use |
|---|---|---|
| `inline` (default) | The app lifespan starts the worker as a background thread whenever durable storage is active. Stops cleanly with the app. | Single-process stations — the normal case. No extra service to run. |
| `external` | The app never runs the loop. Run `python -m civiccast.live.finalization_worker` as a separate process (same environment: `DATABASE_URL` + the knobs below). | Scale-out, or isolating ffmpeg work from the API process. Run exactly **one** worker process: the current claim semantics are single-worker (a second concurrent worker can double-encode). |
| `off` | The loop never runs anywhere. Status endpoints stay readable. | Maintenance windows; debugging. Sessions accumulate in `ending` while off. |

External mode supports `--once` (single scan, then exit) for smoke checks and
cron-style operation:

```powershell
$env:DATABASE_URL = 'sqlite:///C:\path\to\civiccast.db'   # or postgresql://...
python -m civiccast.live.finalization_worker --once
```

An invalid mode value fails app startup with a clear error — fix the variable
rather than expecting a silent default.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_FINALIZATION_WORKER` | `inline` | Deployment mode (above). |
| `CIVICCAST_LIVE_MANIFEST_BASE_URL` | unset | Public base URL under which packaged live recordings are served, e.g. `https://media.example.org/live`. When set, a completed job writes `<base>/<live_session_id>/playlist.m3u8` to `assets.manifest_url` and the asset can pass publish readiness. When unset (and no CDN provider is configured), the worker falls back to VOD local-serve — see "Serving packaged output" below — rather than leaving `manifest_url` empty. |
| `CIVICCAST_LOCAL_MEDIA_BASE_URL` | `http://127.0.0.1:8000` | Base URL for VOD local-serve (see below). Only used when neither `CIVICCAST_LIVE_MANIFEST_BASE_URL` nor a CDN provider is configured. Override when the app is fronted by a reverse proxy or bound to a non-default host/port. |
| `CIVICCAST_FINALIZATION_SETTLE_SECONDS` | `30` | How long the recording's byte size must be stable before finalization starts. Keep at or above your recorder's flush interval; too low risks packaging a still-growing file. |
| `CIVICCAST_FINALIZATION_MAX_ATTEMPTS` | `3` | Attempts before a job is terminal `failed`. |
| `CIVICCAST_FINALIZATION_BACKOFF_SECONDS` | `30` | Base for exponential retry backoff (30s, 60s, 120s, …). |
| `CIVICCAST_FINALIZATION_POLL_SECONDS` | `5` | Scan interval of the worker loop. |
| `CIVICCAST_FINALIZATION_RUNNING_LEASE_SECONDS` | `900` | Self-healing lease: a job stuck in `running` longer than this (the process crashed mid-attempt) is treated as a failed attempt and requeued automatically. Set to at least 2× your longest expected encode. |
| `CIVICCAST_FINALIZATION_NEVER_APPEARED_SECONDS` | `1800` | Deadline after end-broadcast for the recording file to appear. If nothing is ever observed, the job fails terminally with `recording.never_appeared` and the expected path in the reason — instead of pending silently forever. |
| `CIVICCAST_CDN_PROVIDER` (+ provider credentials) | `off` | When a CDN is selected (see `docs/ops/cdn-and-providers.md`), the worker uploads each packaged HLS tree to the CDN under `live/<live_session_id>/…` (segments first, manifest last) and sets `assets.manifest_url` to the CDN public URL — which takes precedence over `CIVICCAST_LIVE_MANIFEST_BASE_URL`. A failed upload is a retryable `cdn.upload_failed` failure; the local package is kept. The external worker process reads this from its own environment, the same as the app. |

The status read endpoints use the same settings as the loop, so what operators
see always reflects the running configuration.

## Serving packaged output

The worker writes HLS output next to the recording:
`<recording-target>/<live_session_id>-hls/playlist.m3u8` plus variant
renditions.

**Stock install (no CDN, no `CIVICCAST_LIVE_MANIFEST_BASE_URL`):** the app
serves this itself. `civiccast.stream.media_router` mounts
`GET /media/vod/{asset_id}/...`, resolving each request to the exact package
directory the worker wrote (via the finalization job's
`local_package_manifest_path`), with immutable long-TTL caching on segments
and correct `.m3u8`/`.ts` content-types. Completed finalizations publish
`manifest_url = http://127.0.0.1:8000/media/vod/<asset_id>/playlist.m3u8` by
default (loopback `http://` is exempted from the https-only rule for this
case — see `docs/ops/cdn-and-providers.md`). No configuration is required
for a resident's browser to play a finished recording out of the box.

**A real external host** (a domain residents can reach, TLS-terminating
reverse proxy, or a CDN) still needs one of:

1. Serve each `<live_session_id>-hls` directory under a web server / reverse
   proxy / CDN so that `https://<your-media-host>/<live_session_id>/playlist.m3u8`
   resolves to the corresponding `playlist.m3u8`, then set
   `CIVICCAST_LIVE_MANIFEST_BASE_URL=https://<your-media-host>` and restart.
2. Or configure a CDN (`CIVICCAST_CDN_PROVIDER=bunny|cloudflare_r2`): the
   worker uploads each package to the CDN itself and publishes the CDN URL.
   See `docs/ops/cdn-and-providers.md`.

Either takes precedence over local-serve.

## Reading status

- `GET /api/staff/live/finalizations` — all job rows (staff bearer token
  required).
- `GET /api/staff/live/sessions/{id}/finalization` — one session's job, 404
  until the worker first observes the `ending` session (within one poll
  interval of end-broadcast).

States: `pending` (waiting for the file to appear/settle), `running` (attempt
in progress), `failed` (last attempt failed — retries automatically while
`attempts < max_attempts` and `next_attempt_at` is set; terminal when attempts
are exhausted), `completed`. The payload's `terminal` field says directly
whether further automatic transitions will occur — consumers never need to
re-derive it from `attempts`/`next_attempt_at`.

On failure, `failure_code` is a stable machine identifier, `failure_reason` is
operator-ready copy, and `failure_detail` carries raw diagnostics (may include
server paths):

| `failure_code` | Meaning / action |
|---|---|
| `recording.never_appeared` | No recording file was found within the deadline; the expected path is in the reason. Check the recorder and the recording target. |
| `recording.not_local` | The resolved recording location is not a readable local path. Check the recording target configuration. |
| `probe.failed` | The recording file could not be read (incomplete/corrupt). The file is kept. |
| `finalize.invalid_trim` | The stored trim window is invalid. Fix the trim values. |
| `package.failed` | HLS packaging failed; the original recording is safe. Retries are automatic. |
| `worker.interrupted` | The app/worker restarted mid-attempt; recovered automatically by the running-lease and retried. |
| `internal.error` | Unexpected error; see server logs. |

## When a job is terminal `failed`

A terminal failure means the recording was **not** packaged; the original
recording file (if it exists) is untouched on disk. Read `failure_reason` on
the status payload, fix the underlying cause (missing/corrupt recording, wrong
recording target, ffmpeg failure — check the app/worker logs for the full
traceback), then retry:

- **Operator console:** the Live room's "Recording finalization" panel shows
  the failure reason and a **Retry finalization** button for terminal
  failures.
- **API:** `POST /api/staff/live/sessions/{id}/finalization/retry`
  (meeting-operator role; 409 while an attempt is running or after
  completion). The job resets to `pending` with a fresh attempt budget and
  the worker re-attempts it on its next scan.

## Logging and boot notes

- The worker logs through the `civiccast.live.finalization_worker` logger:
  thread start/stop and (from the hardening pass) attempt activity and
  failures. Run the app with INFO logging to see it.
- Every app boot without `CIVICCAST_AUTH_ACK=1` prints the staff-auth posture
  warning; set the variable once you've confirmed loopback/reverse-proxy
  posture (see `docs/ops/staff-route-protection.md`). This is unrelated to the
  worker but appears in the same logs.
