# CivicCast Captions

The captions module begins the 0.5 release rung. The current slices ship the
backend contract, optional faster-whisper model execution, review queue API,
operator review UI, HLS WebVTT publication helpers, and resident portal
caption controls that later live capture consumes.

Current surface:

- `CaptionRuntime` protocol for runtime adapters.
- `FasterWhisperRuntime` lazy adapter for the optional `faster-whisper`
  package. Default installs stay lightweight; hosts that execute local caption
  models install `civiccast[captions-runtime]`.
- `CaptionStabilizer`, which commits text only after repeated stable hypotheses
  and never rewrites already-committed live cues.
- WebVTT rendering helpers for committed cues.
- Custom vocabulary / initial prompt model passed through the runtime boundary.
- `CaptionPipeline`, which runs a runtime through the stabilization layer,
  prepares stable cue payloads for the review queue, and can rewrite an HLS
  package with WebVTT subtitle tracks once stable cues exist.
- `LiveCaptionWorker`, the live-worker seam that keeps one pipeline instance
  alive across audio batches, persists stable cues into the review queue, and
  optionally rewrites the HLS caption track as cues commit. This is the path a
  real live-source worker uses after extracting mono PCM chunks from the
  broadcast audio.
- The **offline (VOD) caption job** — `civiccast.captions.vod` +
  `civiccast.captions.vod_job` — CivicCast One's keystone K3. Live captioning
  is the accessibility path; this is the legal one: captions on the file the
  station publishes. Approving publish queues a durable
  `offline_caption_jobs` row; the worker extracts mono 16 kHz caption audio
  from the recording (the same shape the live tap forks), runs it through the
  same runtime/pipeline/review-queue seam, and — only after an operator has
  decided on every queued cue — attaches the approved/edited text to the
  packaged VOD as a segmented WebVTT track plus a flat whole-recording
  `captions/captions.vtt`. Rejected cues never publish. Two details differ
  from live and are deliberate: offline runs the stabilizer at
  `stable_windows=1` (each region of a finite file is transcribed exactly
  once, so `low_confidence` reflects the model rather than a flush artifact),
  and publication is gated on review per spec §4.1. Ops guide:
  `docs/ops/background-workers.md`.
- `CaptionTapWorker`, the native multi-channel worker that consumes settled WAV
  segments concurrently, retains the exact reviewed audio, and atomically
  publishes committed cues to each egress channel's `captions/active.vtt`.
  Backlog beyond the configured bound fails closed: the live sidecar is
  cleared, stale segments are discarded (never transcribed, so never
  reviewable, and no retention clock would have covered them), and the channel
  is PAUSED for an exponentially growing window
  (`civiccast/captions/tap_backoff.py`: 60s, 120s, 240s ... capped at 900s)
  rather than retried on the next scan. `runtime-status.json` carries the
  channel's state -- `within-capacity`, `paused` (backing off, with
  `resume_in_seconds` and `consecutive_overloads`), `overloaded`,
  `storage-refused`, or `disabled` (the operator switched live captions off in
  the station profile) -- and is rewritten only when that state changes or on
  a 30-second heartbeat, never once per scan. The overload is logged once per
  pause at WARNING; it was previously CRITICAL on every scan, which on a
  three-channel CPU-only station meant a caption line every ~30 seconds
  burying the playout failure it was competing with. Captions are best effort
  and playout wins: see the ASR concurrency bound and CPU sizing in
  `docs/ops/background-workers.md`.
- Caption benchmark helpers plus `scripts/benchmark-caption-runtime.py`, which
  load mono signed 16-bit PCM WAV fixtures, run the same runtime adapter used by
  live captions, and emit JSON evidence with transcript text, optional WER,
  latency, chunk count, and best-effort GPU memory samples.
- Staff review queue endpoints under `/api/staff/captions/review-items` for
  adding stable cues, listing/filtering pending work, and approve/edit/reject
  decisions while preserving the original machine cue text and the exact
  private audio evidence. Low-confidence approvals require an explicit
  acknowledgement.
- Operator Review queue UI for searching, filtering, approving, editing, and
  rejecting caption review items with actionable loading, empty, error, and
  low-confidence partial states.
- HLS WebVTT publication helpers that write segmented caption playlists under
  `captions/{language}/` and rewrite the multivariant manifest with
  `EXT-X-MEDIA TYPE=SUBTITLES`.
- Resident portal caption controls for HLS subtitle tracks discovered from the
  multivariant manifest.

Runtime notes:

- The adapter defaults to `large-v3`, `device="auto"`, and
  `compute_type="int8"`. CPU CTranslate2 does not support `int8_float16`; CUDA
  proof may explicitly select it where the installed runtime supports it.
- Native packaged captions set `CIVICCAST_WHISPER_MODEL_PATH` to the exact
  pinned local tree for the caption tier the station selected, and
  `CIVICCAST_CAPTION_TIER` to that tier's id. A configured local path is
  opened `local_files_only` and missing files fail instead of downloading at
  first use.
- The completeness check is **per tier**: each tier's required file list is
  derived from that tier's own pinned inventory in
  `civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY`, never from one
  tier's shape applied to all of them. The `medium` floor tier ships
  `vocabulary.txt` and no `preprocessor_config.json`; `large-v3` ships
  `vocabulary.json` and a preprocessor config. A declared tier that disagrees
  with the model directory it points at is refused as a cross-tier swap.
- `CIVICCAST_WHISPER_CPU_THREADS` and `CIVICCAST_WHISPER_NUM_WORKERS` configure
  the shared model executor. `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`
  configures concurrent channel scans, and
  `CIVICCAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS` sets the fail-closed backlog
  bound. `CIVICCAST_WHISPER_NUM_WORKERS`,
  `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`, and
  `CIVICCAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS` must be positive integers
  (minimum 1); `CIVICCAST_WHISPER_CPU_THREADS` must be a non-negative integer
  (minimum 0 -- `0` means "every core" and is the batch/VOD default, honoured
  as before). Item 79 (2026-09) adds a live-only exception: for the **live**
  caption tap specifically, `CIVICCAST_WHISPER_CPU_THREADS` is CLAMPED rather
  than fatal -- an unparseable or negative value falls back to a safe
  default with a warning instead of raising, `0` ("every core") is refused
  the same way and falls back too, and any value above `2` is capped at `2`
  -- so this variable can no longer hand the live tap "every core" or take
  an activated station off air over a typo. The batch/VOD runtime keeps the
  original fail-fast (raise) behaviour on a bad value. See
  `docs/ops/background-workers.md` for the full env-var reference table
  (including the live-only `CIVICCAST_CAPTION_TAP_CPU_THREADS`) and
  `civiccast/captions/runtime.py`'s `_resolved_whisper_cpu_threads_env` for
  the implementation.
- CivicCast converts each mono PCM s16le chunk to a temporary WAV before
  calling `WhisperModel.transcribe`, then offsets segment timestamps back to
  the chunk's live timeline.
- Custom vocabulary terms and the operator-provided initial prompt are passed
  through as the faster-whisper `initial_prompt`.
- Empirical release evidence should run the Blackwell verifier first, then run
  the benchmark on a representative mono 16-bit PCM WAV fixture. Example:
  `python scripts/benchmark-caption-runtime.py --audio docs/releases/evidence/v0.5-caption-fixture.wav --truth docs/releases/evidence/v0.5-caption-fixture.txt --output docs/releases/evidence/v0.5-caption-benchmark.json --model large-v3 --device cuda --compute-type int8_float16 --vocabulary-term "Councilmember Rivera"`.
  A green benchmark record must include non-empty transcript text, latency,
  optional WER when a truth transcript exists, and GPU samples on NVIDIA hosts.
- The manual `benchmark-caption-runtime` GitHub Actions workflow runs this
  path on the RTX 5070 self-hosted runner. It installs any missing fixture
  tools (`espeak-ng`, `ffmpeg`), creates a small civic-meeting speech fixture,
  verifies the CUDA runtime, runs the benchmark, and uploads the JSON evidence
  artifact for the v0.5 release log.
- `scripts/prove-live-caption-path.py` runs the deterministic live path proof:
  a fake runtime feeds repeated live observations through `LiveCaptionWorker`,
  a stable cue is persisted to the review queue, the HLS manifest is rewritten
  with a WebVTT subtitle track, and a later conflicting observation is checked
  to prove already-committed on-screen text is not retroactively rewritten.
