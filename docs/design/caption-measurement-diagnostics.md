# Caption measurement diagnostics (U73)

This is instrumentation, not a caption-drop fix. Decoding configuration, model
kwargs, transcript hypotheses, discard thresholds and scheduling are unchanged.

The bounded `Caption tap shed diagnostic <json>` INFO line reports the first
over-limit scan and an actual catch-up shed. Each channel/event is limited to
one line per 30 seconds by default. At most 16 channels, eight recent batches per
channel and eight ffmpeg process entries are retained; probes are cached for two
seconds and degrade to unavailable. No speech text or audio is logged.

`CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC=0` (also false/no/off) disables it.
The legacy `CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC` spelling remains a fallback;
the existing environment resolver gives the current spelling precedence and
warns once on a conflicting or deprecated legacy value. A blank current value
falls through to the legacy value.

Each batch retains the compatible wait_s/feed_s/asr_s/stabilize_s fields.
asr_s covers the complete process_batch call, not just ASR decoding. New fields:

- transcribe_s: wall time in the model call plus each lazy generator next(). It
  excludes model loading, audio preparation, hypothesis conversion and consumer
  pauses (including VOD consumer pauses).
- duration_after_vad: optional model-reported audio duration after VAD.
- max_segment_temperature: maximum valid non-negative segment temperature,
  not a changed decode setting or an unconditional diagnosis of retries.
- other_process_batch_s: asr_s minus transcribe_s minus stabilize_s. This residual
  includes all other process_batch work. It cannot alone identify persistence or
  publication stalls. Unknown/invalid terms or negative residuals produce null.

Optional numbers reject non-finite, negative and unrepresentable metadata.
Records retain only plain scalar values, not segment/audio objects. Runtime
metrics are thread-local copies of the latest chunk; transcribe clears them
before prompt/audio preparation and each chunk. The tap also clears them before
phase entry or evidence-factory evaluation, so predecode failures cannot reuse a
previous batch's measurements. Runtime exceptions still propagate unchanged.

## Later measurement plan (requires separate live authorization)

Before installing anything, record the exact candidate and loaded module/process
identity. Observe several live-shaped windows across all channels with decoding
unchanged; correlate shed and streak-start events with retained batch timings,
queue ages, CPU/thread/ffmpeg/GPU evidence. Compare decode time to post-VAD audio
and temperature metadata, and distinguish model loading/audio preparation/other
process_batch overhead from decoding. A large residual warrants separately
timing its contributing phases, not labeling it a persistence stall. Keep an
unchanged-decode control and quantify diagnostic overhead. No installation,
station observation, performance improvement or root-cause claim is made here.

This repository candidate changes runtime.py, tap_worker.py and adds
tap_shed_diagnostic.py under civiccast/captions; that is not an installation
recipe. First inventory and diff the installed C17 files against this accepted
repository candidate: the installed tree already has a collector and may have
installed-only functionality that a blanket overwrite would remove. Derive a
compatible measurement-only carry only after that comparison, preserving
model/temperature/preparer behavior. Use a 20-minute observation window, then
stop and review even if no
shed occurred. Probes run synchronously at the rare event on the scan path:
psutil/NVML calls have no timeout, so bounded record counts are not a wall-time
latency guarantee. Watch scan/heartbeat latency and playout health; stop sampling
if diagnostic latency exceeds 100 ms, a new heartbeat/playout stall appears, or
metadata output becomes missing/non-finite. Disabling the diagnostic is the
first stop action; a hung synchronous probe needs the separately authorized
service recovery/rollback procedure and cannot be interrupted by that switch.
Preserve exact pre-install file backups and restore them under separate
authority; the existing installed collector is restored, not deleted. No
installed file is presumed absent from this repository's add-file status.

Only repeated shed-correlated evidence that isolates a particular decode or
other-process-batch stage, against the unchanged control, justifies proposing a
behavior change. A large residual, high temperature or busy ffmpeg list alone
is insufficient. Offline source rollback is this unit's c7492118 base; live
rollback is outside this unit because nothing was installed.
