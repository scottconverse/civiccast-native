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

## Logical batch attribution (U82)

Retained shed timing rows from the dispatched tap path also carry the existing
batch_id and captured generation, plus segment_indices containing exactly the
one attempted segment index. A dispatch may select multiple, noncontiguous
segments: its parent batch diagnostic has the selection list, while each shed
timing row describes one process_batch invocation. Partial completion or a
generation reset produces rows only for actual attempts. A decode finishing
after a reset retains its original generation, not the newer current session.
The opt-in batch diagnostic need not be enabled for the dispatch ID to reach
the shed row. No decoding, scheduling, retention, or reset policy is changed.

Legacy direct callers without identity, or calls with invalid/partial identity,
retain the old timing-only row shape. Valid IDs are retained verbatim, capped at
256 characters, and match the channel/generation and existing g/b/n syntax.
Generation, index, first index, and positive selection count are bounded by
2**63-1; bool and arbitrary objects are rejected without stringifying them.
The first index cannot exceed the current index; a single-segment selection
must match it. Multi-segment membership comes from the worker's selected list,
not a guessed contiguous range. No new text, audio, paths, filenames, or prompts
are retained. Existing eight-row/sixteen-channel bounds and log rates remain.

These IDs identify a logical selection, not a unique attempt or replay. Failed
same-selection retries can repeat an ID in the same process/generation, and IDs
can repeat after restart; they do not encode the complete selection sequence.
Preserve enclosing pid/time/loaded-code provenance and acknowledge that retry
ambiguity when joining evidence. Shed emission is a retained snapshot, not a
delta: later events may repeat the same rows and must not be summed blindly.
The frozen out-of-product U80 sanitizer does not whitelist these added fields;
its future evidence-capture adaptation is separate and unrun, not changed here.

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
protection or zero overhead. Background completed probe time/inflight age is WATCH
evidence, not proof the caller waited. Stop an authorized measurement trial when
consumer sampling or measured proof capture/dispatch exceeds100ms, a new
heartbeat/playout stall appears, or exercised required metadata is missing/non-finite.
Disabling skips future collector work, but cannot interrupt a running native probe;
recovery/rollback remains separately authorized.
Preserve exact pre-install file backups and restore them under separate
authority; the existing installed collector is restored, not deleted. No
installed file is presumed absent from this repository's add-file status.

## Optional selected executable-code receipt (U75/U79)

Proof receipts default OFF. Set `CIVICCAST_CAPTION_EXECUTABLE_PROOF` in the process
startup environment before importing this helper: `1/true/yes/on` enable it;
case/whitespace normalize, all other/absent values disable. This new flag has no
historically deployed one-C alias; `CIVICAST_CAPTION_EXECUTABLE_PROOF` is not read.
The flag is captured once at helper import, not refreshed per batch or promised to
follow later dotenv/config edits. Normal disabled hooks perform no snapshot,
clock, reservation, thread or logging work. Existing shed-switch legacy behavior
is unchanged. Proof must be explicitly enabled in an authorized trial; missing or
disabled receipts never count as code confirmation.

When enabled, actual tap _process_channel, runtime transcribe (first generator next)
and collector probe refresh each capture at most one process-wide fixed-key receipt:
`Caption diagnostic executable receipt <json>`. PID/process nonce join the three
receipts. Caller captures its immutable executing CodeType and fixed selected
CodeTypes at that boundary, without executing owner property getters; background
work never looks up a later owner. No owner, frame, bound method, audio or model is
handed to a worker. `executing` hashes actual frame code; `selected` hashes captured
anchors, not a claim every selected method was exercised. A replaced lookup at
capture reports mismatch/unavailable, not ok; a later patch cannot relabel capture.

At most three one-shot daemon threads/process (one per fixed key), no general
executor, queue, periodic monitor or replacement while stuck. Caller never joins
hash, receipt clock, JSON or logger work. Constructor/start failure reserves its
key permanently; unavailable or absent confirmation is not acceptance. A contended
nonblocking reservation can return unconfirmed until a later natural invocation.
Worker waits at most2s for a bounded Event/single-scalar dispatch-completion handoff;
timeout yields no receipt/confirmation, never a consumer wait. A stuck worker may
retain its bounded immutable code snapshot, not product owner/audio. Thread.start,
trusted builtin clock, GIL and OS scheduling are not cancellable/hard-real-time.

`caller_capture_dispatch_elapsed_s` measures enabled hook capture through actual
Thread.start completion with the trusted builtin perf_counter. Its final scalar/
Event publication is outside that stopwatch; external whole-call checks cover it.
`background_fingerprint_elapsed_s` independently measures worker receipt/hash work
after completion handoff, before JSON/logger. Both finite/nonnegative or null on
clock faults. The old synchronous `elapsed_s` field is not relabelled as caller
time. Worker-injected clock/hash/logger delays cannot force caller waiting; a
trusted builtin caller clock that genuinely hangs can, so no hard latency guarantee.
Caller timing>100ms/exercised missing timing stops a proof trial; background duration
is WATCH and not a caption-delay cause. Exceptions preserve decode/errors unchanged.

selected-code-v1 hashes semantic bytecode, exception tables, typed constants/nested
code, names and argument/closure/flags metadata. It excludes filenames and line
positions. Compare against offline compiled accepted source under the exact same
Python version/cache tag and optimization mode; compiled_anchors discovers the
selected qualified names without executing source. Commit identity belongs in the
offline artifact manifest, not a self-referential embedded source hash. Origin and
co_filename are bounded location metadata, never loaded-code proof by themselves.
Hash work has fixed256KiB/4096-node/depth32 budgets; only digests are logged, not
constants, audio or transcripts. Async receipt timing does not diagnose scheduler,
GIL or cold-start behavior and does not fix caption drops.

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
