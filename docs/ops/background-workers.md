<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Background Workers

CivicCast runs three lifespan-supervised background services when durable
storage is active. Each follows the same deployment shape: env-selected mode,
fail-fast settings validation at startup, a loop that survives and logs scan
errors, clean stop on shutdown.

| Worker | What it does | Mode variable (default) |
|---|---|---|
| Recording finalization | Turns ended broadcasts into recorded, packaged VOD assets. Full guide: [Finalization Worker Runbook](finalization-worker-runbook.md). | `CIVICCAST_FINALIZATION_WORKER` (`inline`; also `external`/`off`) |
| ActivityPub delivery retry | Re-delivers failed follower deliveries with bounded exponential backoff; dead-letters after max attempts. | `CIVICCAST_ACTIVITYPUB_RETRY_WORKER` (`inline`; or `off`) |
| Retention review | Flags assets whose retention schedule expired into the records-clerk disposition queue. **Never deletes anything.** | `CIVICCAST_RETENTION_WORKER` (`inline`; or `off`) |
| Offline caption job | Captions a published recording: transcribe → operator review queue → reviewed WebVTT attached to the published VOD. | `CIVICCAST_OFFLINE_CAPTION_JOB` (`inline`; or `off`) |

## ActivityPub delivery retry

A delivery that fails at publish time (network error or HTTP >= 400) is
queued durably in `activitypub_delivery_retries`. The worker retries due rows
and records successful retries in the normal delivery log.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_ACTIVITYPUB_RETRY_POLL_SECONDS` | `60` | Scan interval. |
| `CIVICCAST_ACTIVITYPUB_RETRY_BACKOFF_SECONDS` | `120` | Base for exponential backoff (120s, 240s, 480s, …). |
| `CIVICCAST_ACTIVITYPUB_RETRY_MAX_ATTEMPTS` | `8` | Attempts (including the original send) before a row is dead-lettered. |

Dead-lettered rows stay in the table with the last status code and error for
inspection; they are never rescanned automatically. To replay one after fixing
the follower-instance issue:

- **Operator console:** the Federation screen's "Delivery retry queue" panel
  lists pending/dead-lettered deliveries with a **Replay delivery** button.
- **API:** `GET /api/staff/activitypub/delivery-retries` to inspect the queue;
  `POST /api/staff/activitypub/delivery-retries/{retry_id}/replay` (409 unless
  dead-lettered) grants a fresh attempt budget and the worker re-delivers on
  its next scan.

## Channel automation driver (cable automation)

The app drives enabled egress channels 24/7 — the `civiccast egress run` CLI
is no longer required for normal operation (it remains for external-process
deployments). Each poll processes every enabled channel's durable command
queue and supervises its encoder. Channels with `auto_start` set on their
egress config are brought back on air automatically after an app or machine
restart, and join-in-progress source planning resumes the current program at
the wall-clock offset so the channel stays on its published log. A channel
on fallback slate is reloaded the moment a scheduled program becomes due.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_CHANNEL_AUTOMATION` | `inline` | `inline` runs the driver as a lifespan thread; `off` disables it (use the CLI worker instead). |
| `CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS` | `2` | Poll cadence per pass over all enabled channels. |
| `CIVICCAST_EGRESS_WORK_DIR` | platform default | Directory for prepared segments and generated slates. |

Gaps between scheduled programs fill per the channel's `fill_policy`
(egress config): `slate` (default) or `bulletins` — a rotation of branded
slides rendered from the channel's APPROVED community bulletins
(`/api/staff/cg/channels/{id}/bulletins`). With zero approved bulletins the
channel falls back to the plain slate; an unchanged board is served from a
per-slide render cache.

Do not run the inline driver AND a CLI egress worker for the same channels
at once — two daemons would race on the same command queue.

## Program-log materializer (cable automation)

Operator-defined recurring program slots (`/api/staff/programlog/slots`)
materialize into real premiere schedule items over a rolling horizon, so a
cable channel always has upcoming programming for the playout path. Skipped
occurrences (schedule conflicts, unplayable assets) are recorded with their
reason and surfaced in the channel log — never retried silently.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_PROGRAM_LOG_WORKER` | `inline` | `inline` runs the materializer as a lifespan thread; `off` disables it (the `/materialize` endpoint still works on demand). |
| `CIVICCAST_PROGRAM_LOG_POLL_SECONDS` | `300` | Scan interval. |
| `CIVICCAST_PROGRAM_LOG_HORIZON_HOURS` | `72` | How far ahead occurrences are materialized. |

## Subscriber webhook delivery retry

A real webhook delivery that fails at dispatch time (network error or HTTP
>= 400; only possible when `CIVICCAST_PROVIDER_WEBHOOK=real` — the default
mock never fails) is queued durably in `subscription_webhook_retries`. The
row carries only the subscription id and the notification payload: the
webhook URL and per-subscription signing secret stay sealed in the
subscriptions table and are reopened at send time. A subscription that
unsubscribed after the failure is dead-lettered without being called.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_WEBHOOK_RETRY_WORKER` | `inline` | `inline` runs the worker as a lifespan thread; `off` disables it. |
| `CIVICCAST_WEBHOOK_RETRY_POLL_SECONDS` | `60` | Scan interval. |
| `CIVICCAST_WEBHOOK_RETRY_BACKOFF_SECONDS` | `120` | Base for exponential backoff (120s, 240s, 480s, …). |
| `CIVICCAST_WEBHOOK_RETRY_MAX_ATTEMPTS` | `8` | Attempts (including the original send) before a row is dead-lettered. |

Dead-lettered rows stay in the table with the last status code and error for
inspection; they are never rescanned automatically.

## Retention review

The worker scans `assets.retention_until` and flags expired, non-`permanent`
assets exactly once into `asset_disposition_reviews`. Records clerks read the
queue at `GET /api/staff/records/disposition-queue`.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_RETENTION_POLL_SECONDS` | `3600` | Scan interval (hourly is plenty; schedules are measured in days). |

**Disposition is a human decision.** The retention presets ship with
"confirm with your records officer" disclaimers; automatic purge is an
explicit pending product decision. When a flagged asset's disposition is
decided, act per your station's records policy — purge, extend
`retention_until`, or apply a litigation hold — and keep the disposition
record with the station's retention files.

## Live caption tap

Beta B6 (product decision #1, option A — egress audio fork). When configured,
the egress encoder forks a low-bitrate audio-only output of the same ffmpeg
process: rolling mono 16 kHz s16le WAV segments under
`CIVICCAST_CAPTION_TAP_DIR/<channel_id>/chunk-NNNNNN.wav`. The caption tap
worker consumes a segment only once a newer-numbered sibling exists (so a
half-written file is never read), feeds it through the existing live caption
seam (pipeline → two-window stabilization → **durable review queue**), then
moves it to `processed/`; unreadable segments go to `quarantine/` and never
kill the scan.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_CAPTION_TAP` | `off` | `inline` runs the worker as a lifespan-supervised thread; `external` means you run `python -m civiccast.captions.tap_worker` as a separate process (same env + `DATABASE_URL`); `off` disables the worker (the egress fork still writes segments if the tap dir is set). |
| `CIVICCAST_CAPTION_TAP_DIR` | unset | Tap root shared by the egress fork and the worker. Required when the mode is not `off`; setting it also enables the egress fork. |
| `CIVICCAST_CAPTION_TAP_SEGMENT_SECONDS` | `5` | Segment length — the floor of the caption latency budget (tap → transcribe → stabilize → review queue). |
| `CIVICCAST_CAPTION_TAP_POLL_SECONDS` | `2` | Worker scan interval. |

**Why off by default:** live transcription needs the local faster-whisper
model runtime. Enabling `inline` without the model installed fails fast at
startup rather than silently captioning nothing. Cues land in the operator
caption review queue (`caption_review_items`) exactly like the proof path —
review and publication flow is unchanged.

## Offline caption job (published-file captions)

The live tap above is the accessibility path. This one is the **legal**
path: captions on the file a station publishes. Approving publish for a
recording queues a durable job in `offline_caption_jobs`; the worker
transcribes the recording's audio with the station's staged caption model
and files every cue in the same operator review queue the live path uses.

Every worker tick also runs the retained-audio-evidence retention sweep
(`CaptionEvidenceRetentionPolicy.from_system`, `civiccast/captions/retention.py`)
against the same review queue -- the same 90-day/free-space lifecycle the
live tap's readiness tick already enforced, but previously only from the
live tap: a station running offline/VOD captioning with no airing live
channel never pruned these per-cue WAVs (audit finding, MAJOR), so they grew
unbounded on disk. A sweep *failure* (an exception, including building the
policy the first time) never fails the caption job it runs alongside; it is
logged and retried on the next tick.

A clean sweep *result* is a different thing from a failure, and is honored:
when the sweep reports the storage is not ready (the free-space reserve
would be breached, or retained evidence is still over the storage cap even
after pruning everything eligible), `run_once` skips every due job that
tick -- neither stage-one transcription (which writes new evidence WAVs)
nor stage-two publish runs -- exactly mirroring
`CaptionTapWorker.run_once`'s own `if not retention.ready: ...` gate before
any channel work (audit finding, P1; the result used to be discarded and
every due job transcribed regardless of what the sweep found).

The sweep's free-space reserve and storage-cap decisions are measured
against the volume that actually holds this worker's evidence WAVs: the VOD
package root (`CIVICCAST_VOD_PACKAGE_DIR`, or `CIVICCAST_UPLOAD_DIR` +
`.civiccast-packages` -- the same resolution
`civiccast.schedule.paths.resolve_vod_package_root` gives every queued
job's own `package_dir`), not the live egress work directory
`CaptionTapWorker` measures (audit finding, P1; those can be different
filesystems, and reading the wrong one could let free-space or the storage
cap silently blow out on the volume evidence is actually written to).

Evidence WAVs shared by several cues from the same ASR window (one
low-confidence chunk that produced multiple cues, so
`_offline_audio_evidence_factory` / `CaptionTapWorker._audio_evidence_factory`
attached the same file to each) are retained until the *latest* of those
cues' resolutions, not the earliest: `_discover_candidates`'s per-path
coalescing tracks the maximum `resolved_at` across every review row sharing
a path, order-independent (audit finding, P2; fixed directly rather than
deferred -- the change only ever delays a prune, never advances one, so it
cannot make live evidence disappear earlier than before). This is shared
code path for both the live tap and the offline job.

The job has two stages because operator approval sits between them
(spec §4.1 — no AI-generated text reaches a public surface unreviewed):

1. `pending` → transcribe and queue for review. **Publishes nothing.**
2. `awaiting_review` → re-checked each poll. Once every queued cue has an
   operator decision, the approved/edited text is attached to the packaged
   VOD: a segmented WebVTT track declared in the multivariant manifest
   (`captions/<lang>/playlist.m3u8`) plus a flat whole-recording
   `captions/captions.vtt` for records requests. Both are served by the
   existing published-gated `/media/vod/{asset_id}/...` route.

Rejected cues are dropped. A queue that is rejected in full completes with
the recording left uncaptioned rather than publishing text an operator
refused.

**When captions exist relative to publication.** Approving publish makes the
recording public immediately; the caption job runs afterwards, because a
public record must not wait days on caption review. The operator-facing
statement of this, used verbatim on every surface, is: *the recording is
public immediately; captions attach after review — both languages together,
never English alone.*

Publish-first does **not** mean best-effort. `POST /api/staff/publish/assets/
{asset_id}/approve` queues the caption job **before** it approves anything,
and returns **409** naming the cause if it cannot — no caption job store, no
upload storage, or a failing enqueue. Nothing is published in that case, so
there is no window in which a recording is public with no caption job and
only a log line to say so. The one case that is still a skip rather than a
block is an asset with no local recording file: there is nothing to
transcribe, so no caption job is owed. A portal *retry* that publishes cannot
be pre-checked the same way (the recording is public by the time the retry's
outcome is known), so it raises a 409 that says plainly that the portal
publish succeeded and the caption job did not queue.

**Recorded-Spanish captions (required, not optional).** A published
recording carries an operator-reviewed **Spanish** caption track alongside
English. This is a product requirement, not a station setting: there is no
supported configuration that publishes a caption-eligible recording in
English only, and `CIVICCAST_OFFLINE_CAPTION_SPANISH` no longer disables the
leg (see the variable table below — a false value now stops startup with an
error rather than silently taking effect).

With the Spanish leg running, `awaiting_review`
becomes a two-phase gate. Once the **English** review pass is complete and
something was approved, the approved English cues are translated to Spanish
through the same operator-selected translation tier the live tap uses (local
TranslateGemma by default), and the Spanish cues are queued for their **own**
operator review pass — the Spanish text is AI output too, so spec §4.2's
operator-review-before-publish applies to it. The recording is not published
until **both** passes are complete; then both tracks attach in one manifest
rewrite (English `captions/en/playlist.m3u8` default + `captions.vtt`, Spanish
`captions/es/playlist.m3u8` secondary + `captions.es.vtt`). The two passes are
separated by a `language` column on `caption_review_items` (migration
`0083_caption_review_language`, default `en`); the operator console's review
queue shows an EN/ES badge and a language filter. Spanish review rows are
created `low_confidence=False` (a translation of human-approved English has no
ASR audio to retain), so the low-confidence audio-evidence approval gate
cannot deadlock the Spanish track.

No way the caption pass can come up empty resolves to a green job:

* **No translation runtime available.** The job records an attempt with an
  operator-facing remediation on `last_error` ("CivicCast has no translation
  model available to produce the required Spanish track…"), retries on the
  normal backoff, and lands in `failed` — with that same reason on the row —
  if the runtime is never repaired. Fix it in **Settings → AI Models →
  Translation**, or run `civiccast doctor`.
* **The operator rejected every Spanish cue.** The job stays in
  `awaiting_review` with a remediation on `last_error` and does **not** burn
  the retry budget: the block is a human decision, not a fault. Open the
  caption review queue, filter to Spanish, and edit the cues with the correct
  wording (or approve the ones that are right) — review decisions are not
  terminal, so a rejected row can be edited. Publication continues on the next
  poll once at least one Spanish cue is approved or edited.
* **The operator rejected every English cue.** Symmetric with the Spanish
  case: no English means nothing to translate and no track in either
  language, so the job stays in `awaiting_review` with its own remediation
  rather than completing with zero cues attached. If the audio is genuinely
  unusable, a technical admin cancels the job; the worker will not decide
  that on its own.
* **The translation pass came back short.** `queue_translated_captions`
  writes one review row per cue, so a store failure partway through a long
  meeting leaves fewer Spanish rows than approved English cues. The job
  compares the stored Spanish cue ids against the ids the approved English
  cues *should* produce, queues only the missing ones on the next attempt,
  and fails with a remediation naming the shortfall ("3 of 6") if they still
  cannot be written. A short Spanish track is never attached. Note the
  distinction: an operator *rejecting* some Spanish cues is an editorial
  decision on rows that exist and legitimately yields a shorter track; a row
  that was never created is data loss and blocks.

Both hold states are idempotent — the job row and the log are written once
per state change, not once per 60-second poll.

**CDN republish after review.** Attaching captions rewrites the multivariant
manifest and writes the caption files on **local disk**. When the asset's
package was published to a CDN (`CIVICCAST_CDN_PROVIDER`, or credentials
entered in the setup wizard) before caption review finished, the CDN copy
still has the pre-caption manifest — so the job re-uploads the rewritten
manifest, both segmented caption tracks, and both flat sidecars to the same
key prefix the package was published under
(`civiccast/captions/cdn_republish.py`, through the same
`upload_package_files` helper the finalization worker publishes with, so the
manifest still uploads **last**). Only the caption artifacts are re-uploaded;
the video renditions are unchanged. A republish failure fails the job with the
provider's message on the row rather than completing it — a green job on a
stale CDN manifest would be a false claim that the recording is captioned.
Nothing is uploaded when no CDN is configured, or when this station has no
record of publishing that package to the configured CDN.

| Variable | Default | Meaning |
|---|---|---|
| `CIVICCAST_OFFLINE_CAPTION_JOB` | `inline` | `inline` runs the worker as a lifespan thread. **`off` refuses to start.** Captions on the published file are the legal obligation this job exists to meet, so switching them off is not a supported station configuration; the startup error names the variable and points at `civiccast doctor`. A station with no caption model staged still starts, still queues the work, and reports the gap on each job — it never publishes uncaptioned in silence. The model is loaded lazily, so an idle queue costs nothing. |
| `CIVICCAST_ALLOW_CAPTIONS_OFF_FOR_TESTS` | unset | **Automated tests only; never set this on a station.** The only way to make `CIVICCAST_OFFLINE_CAPTION_JOB=off` take effect. Deliberately a second, coordinated variable with `FOR_TESTS` in its name, so captioning cannot be disabled by a stale runbook or a copied support-thread snippet. |
| `CIVICCAST_OFFLINE_CAPTION_POLL_SECONDS` | `60` | Scan interval. |
| `CIVICCAST_OFFLINE_CAPTION_BACKOFF_SECONDS` | `300` | Base for exponential backoff (300s, 600s, 1200s, …). |
| `CIVICCAST_OFFLINE_CAPTION_MAX_ATTEMPTS` | `4` | Attempts per stage before the job is marked `failed` with its reason. |
| `CIVICCAST_OFFLINE_CAPTION_CHUNK_SECONDS` | `30` | Audio handed to the model per call. Offline has no latency budget, so this is Whisper's own encoder window rather than the live tap's 5 s. |
| `CIVICCAST_OFFLINE_CAPTION_SPANISH` | *(retired — do not set)* | The recorded-Spanish leg always runs. A false value (`off`/`0`/`false`/`no`) now **fails startup** with an error naming this variable, rather than quietly publishing English-only recordings; a true value is accepted as a no-op and logged. Remove it from the station environment. |

Model, device, and compute type are **not** configured here — the job builds
its runtime through the same seam the live path uses, which resolves the
operator-selected caption tier and inherits the hardware-adaptive
device/compute-type the native station runtime published
(`CIVICCAST_WHISPER_DEVICE` / `CIVICCAST_WHISPER_COMPUTE_TYPE` /
`CIVICCAST_WHISPER_MODEL_PATH`).

A `failed` job stays in the table with its reason; the recording remains
published and uncaptioned rather than shipping unverified text. Re-approving
publish for that asset queues a fresh job.

**Operator visibility (staff API):** the router (`civiccast/captions/router.py`)
has no React screen yet, but exposes:

- `GET /api/staff/captions/offline-jobs` — list jobs, optionally filtered by
  `asset_id` and/or `state`, with `state`/`attempts`/`last_error` on each row.
- `POST /api/staff/captions/offline-jobs/{job_id}/retry` — reset a `failed`
  job to `pending` with a fresh attempt budget, without re-approving publish.
  Requires the `records_clerk` role. 409 if the job is not currently `failed`,
  or if a different job is already active (`pending`/`awaiting_review`) for
  the same asset -- retrying a failed job must not put two active jobs on
  one asset (audit finding, MAJOR; see the partial-unique index note
  below).

Only a **Portal** retry (`POST
/api/staff/publish/assets/{asset_id}/surfaces/portal/retry`) queues offline
captioning; retrying any other surface (YouTube, Internet Archive, ...) does
not, even on an asset with no caption job yet, since only Portal success
makes the recording public. This also means retrying an unrelated surface on
an asset whose captions already completed never starts a second
transcription pass for it.

Two concurrent enqueue attempts for the same asset (a publish approval racing
a retry, for instance) cannot both create an active job: a partial-unique
index (`ix_offline_caption_jobs_one_active_per_asset`,
`0075_offline_caption_jobs`) allows at most one `pending`/`awaiting_review`
row per asset. The loser of that race gets back the winning job instead of a
duplicate. The manual retry endpoint above is guarded by the same index --
it pre-checks `active_for_asset` before reopening a `failed` job, and the
durable store also catches the index's `IntegrityError` on the write itself
(closing the gap between that check and the write), so a race there ends in
a clean 409 rather than two active jobs or a raw 500.

### Known follow-ups (out of One v1 scope)

CivicCast One v1 serves uploaded files through the local portal VOD path;
LIVE broadcast and CDN delivery are deferred to keystone K4. The items below
are consequences of that scope line. Item 1 is still open (owner-approved to
defer); item 2 has since been closed.

1. **A live-finalized recording would transcribe but fail to attach.**
   `_queue_offline_captions` (`civiccast/publish/router.py:163`) resolves an
   asset's package directory with `resolve_vod_package_dir`
   (`civiccast/schedule/paths.py`), which only knows the **upload**
   convention: `.civiccast-packages/<asset_id>` under the configured upload
   root. `LiveFinalizationWorker._package_once`
   (`civiccast/live/finalization_worker.py`) packages a live-finalized
   recording somewhere else entirely -- `<recording_path.parent>/<live_session_id>-hls/`,
   persisted on the finalization row's `local_package_manifest_path` -- and
   nothing in the offline caption path consults that record. Stage one
   (transcription) does not depend on the package directory at all, so it
   would still succeed and queue review rows; stage two
   (`OfflineCaptionJobWorker._publish_if_reviewed` in
   `civiccast/captions/vod_job.py`, calling `attach_reviewed_captions`)
   would fail every attempt against a package directory that was never
   written, exhaust its retry budget, and land the job in `failed` with the
   recording permanently uncaptioned. In One v1, offline captioning is only
   reachable from an uploaded-and-published asset (LIVE is out of scope), so
   this path is unreachable today -- it becomes reachable the moment K4
   brings live broadcast back and a live-finalized recording is approved for
   portal publish. The fix, when K4 lands: resolve the package directory the
   same way `civiccast/stream/media_router.py`'s `_package_dir_for_asset`
   already does -- prefer `LiveFinalizationJob.local_package_manifest_path`
   when present, and fall back to the upload convention otherwise.

2. ~~**Caption attach never re-uploads to a CDN.**~~ **Closed.** Caption
   attach still writes only local disk, but `OfflineCaptionJobWorker` now
   re-publishes the rewritten manifest and the new caption files to the CDN
   the package was published to — see "CDN republish after review" above and
   `civiccast/captions/cdn_republish.py`. What remains scope-limited is the
   *reachability*: the only writer of CDN-published VOD packages is
   `LiveFinalizationWorker`, and follow-up 1 above still keeps live-finalized
   recordings out of the offline caption path, so on a One v1 station the
   republisher's lookup finds no CDN-published package and correctly does
   nothing. The code path is proven by the mock-CDN tests in
   `tests/captions/test_caption_cdn_republish.py`, not by a live CDN run.
