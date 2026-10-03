# Caption measurement diagnostics (U73/U75)

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
shed occurred. U75 refreshes process/ffmpeg/GPU evidence on an event-triggered
single-flight daemon per collector. The caller never joins or waits for native
probes. No periodic monitor or replacement thread is created while a probe is
stuck. Fresh cache lasts two seconds; stale/pending evidence is labelled explicitly.
probe_status, probe_refresh_s (completed work), probe_inflight_s (ongoing age),
probe_cache_age_s and sampling_elapsed_s (snapshot retrieval, excluding receipt
hashing/JSON/logging) distinguish these boundaries. Optional invalid times are null.
Initial evidence may be pending; later events report completion, not an invented
sample. Thread-start failures retain their slot rather than retry every event.
GPU device lists are capped at eight and names/reasons at160 characters.

psutil/NVML still have no cancellation; a GIL-holding native call can affect other
Python threads. This is nonwaiting probe isolation, not hard real-time process
protection or zero overhead. Watch scan/heartbeat and playout health; stop sampling
if completed probe time, inflight age or diagnostic sampling latency exceeds100ms,
a new heartbeat/playout stall appears, or required metadata is missing/non-finite.
Disabling skips future collector work, but cannot interrupt a running native probe;
recovery/rollback remains separately authorized.
Preserve exact pre-install file backups and restore them under separate
authority; the existing installed collector is restored, not deleted. No
installed file is presumed absent from this repository's add-file status.

## Selected executable-code receipt (U75)

The actual running tap _process_channel, runtime transcribe (first generator next)
and collector probe refresh each emit at most one process-wide fixed-key INFO line:
`Caption diagnostic executable receipt <json>`. PID/process nonce join the three
receipts. `executing` hashes the caller's actual frame code; `selected` hashes fixed
looked-up methods, not a claim that every selected method was exercised. A replaced
lookup differing from the executing anchor reports mismatch, not ok. Failures are
latched unavailable (or logging unavailable), never retried per batch.

selected-code-v1 hashes semantic bytecode, exception tables, typed constants/nested
code, names and argument/closure/flags metadata. It excludes filenames and line
positions. Compare against offline compiled accepted source under the exact same
Python version/cache tag and optimization mode; compiled_anchors discovers the
selected qualified names without executing source. Commit identity belongs in the
offline artifact manifest, not a self-referential embedded source hash. Origin and
co_filename are bounded location metadata, never loaded-code proof by themselves.
Hash work has fixed256KiB/4096-node/depth32 budgets; only digests are logged, not
constants, audio or transcripts. Receipt elapsed time measures one-shot hashing.

This proves selected executable anchors only: not entire modules, mutable globals,
model weights, native DLLs, or changes after the receipt. Missing confirmation or
unavailable/mismatch is not acceptance. A fresh separate-process import cannot
substitute for station-process receipts. U75 adds diagnostic_identity.py to any
later compatibility/file-manifest assessment; do not deploy using U74's old exact
three-file carry. No live operations were performed for U75.

Only repeated shed-correlated evidence that isolates a particular decode or
other-process-batch stage, against the unchanged control, justifies proposing a
behavior change. A large residual, high temperature or busy ffmpeg list alone
is insufficient. Offline source rollback is this unit's c7492118 base; live
rollback is outside this unit because nothing was installed.
