# CivicCast beta.9 caption-gate ladder: capacity vs gate
## Plain-English comparison (N=1 / N=2 / N=3), 2026-09-18 evening, Mountain Time

## What was asked
Scott's design: run ONE channel for 30 minutes, then TWO, then THREE, measure each,
and determine whether the caption backlog/gate failure is a 16 GB GPU CAPACITY
problem or a GATE/SCHEDULING problem. The cleanest discriminator: if ONE channel
has large VRAM headroom, fast per-segment latency, and the gate STILL fires, it is
not capacity.

## Headline answer
**It is a gate/scheduling problem, not a GPU capacity problem.**
- One channel: ~7.6 GB VRAM free, per-segment latency 5.35 s average, **zero gate trips**, real captions flowing.
- Two channels: **flat** latency (5.32 s avg), VRAM high-water actually LOWER (49.7%), **zero gate trips**, both channels' captions flowing.
- Three channels: latency degrades sharply (avg 7.68 s, max 106.01 s), and the gate trips, clearing captions on all three channels.
- Across ALL THREE rungs the GPU had roughly half its 16,303 MiB free (peak 49.7-53.1%).
  Three channels did NOT consume meaningfully more VRAM than one. The GPU was never
  the constraint; the number of concurrent channels on the single tap thread was.

## The numbers (identical method and 15 s sampling interval in every rung)

| rung | channels | per-seg latency avg | median | p95 | MAX | VRAM high-water | VRAM avg | GPU util avg | GATE TRIPS |
|------|----------|--------------------|--------|-----|-----|-----------------|----------|--------------|-----------|
| N=1  | public                | 5.35 s | 5.33 | 5.47 | 5.51   | 53.1% | 8123 MiB | 42% | 0 |
| N=2  | public + government   | 5.32 s | 5.31 | 5.36 | 5.44   | 49.7% | 7829 MiB | 20% | 0 |
| N=3  | public + gov + education | 7.68 s | 5.32 | 5.41 | 106.01 | 51.7% | 7834 MiB | 19% | 4-5 |

Per-segment latency = wall-clock between a chunk WAV first appearing in the channel
directory and its processed/ counterpart appearing. This delta is dominated by the
~5 s segment fill time, so its absolute value is not pure ASR latency; what matters
is that the SAME method ran in every rung, making the rungs comparable.

## The shape of the N=3 failure
At N=3 the median latency stayed normal (5.32 s) but the average rose to 7.68 s and
the maximum reached **106.01 s**, with a minimum of **0.00 s**. That combination is
the signature of a normally-functioning tap punctuated by long stalls plus instant
drains: when the gate trips it DISCARDS the settled segments (hence 0 s), and the
stall precedes the trip. Gate trips at N=3 occurred on all three channels within
seconds of each other (22:33:57 edu+gov+public at 3 settled; 22:42:50 edu+gov+public
at 4 settled), i.e. one global scan cycle crossing the threshold for every channel.

## Starved vs saturated (tap host CPU, Win32_PerfFormattedData)
| rung | tap-host CPU | reading |
|------|--------------|---------|
| N=1 | 64 / 97 / 136 % of one core; top thread 28-69% | busy, keeping up |
| N=2 | 96 / 74 / 216 %; three threads at 54-74% simultaneously | busy, spread, keeping up |
| N=3 | 107 / 133 / 0 / 117 %; top thread up to 88% | busy; the 0% sample fell inside a gate pause |

The tap host is WORKING in every rung, not starved. It never idles with a growing
backlog. That rules out "the thread is blocked and doing nothing".

## Threading model (established from code, not inferred)
- ONE global serial scan/consume thread for all channels: `run_forever`
  (civiccast/captions/tap_worker.py:574) is a single loop calling `run_once()`;
  `run_once` (:775) walks every channel directory in one call (:834) and issues
  `worker.process_batch([chunk])` ONE segment at a time on that same thread (:1001).
- `num_workers=3` is the CTranslate2/faster-whisper MODEL's internal compute pool
  (runtime.py:161, :734, :824), NOT tap threads and NOT per-channel workers.
- Therefore "three tap threads, one per channel" is not possible as the code stands;
  it would require restructuring the global loop into per-channel work units.

## Which fix candidate the data points at
**Candidate 1 (backoff state machine) first.** Code-level evidence: after a 120 s
pause, `record_within_capacity` needs only `DEFAULT_RECOVERY_SCANS = 3` healthy scans
(~6 s at the 2 s cadence) and then DELETES the channel's state entirely, resetting
`consecutive_overloads` to 0. That is why 110 of 111 trips in the original N=3 run
logged "overload #1": the channel is forgiven and reset to the base delay every
cycle and never escalates. This is contained, has the smallest blast radius, and is
broken on its own terms regardless of threading.
**Candidate 2 (per-channel scan/restructure) is NOT yet supported.** If the single
serialised scan were the binding constraint, latency should have risen from N=1 to
N=2. It did not (5.35 -> 5.32 s) and VRAM peak fell. The constraint only appears at
N=3, so "more threads / more parallelism would help" remains UNSUPPORTED by these
numbers. Candidate 2 should not be attempted on inference.
**Candidate 4 (retention sweep off the critical path) remains UNESTABLISHED.** These
measurements cannot separate the tap's busy time between sweep, ASR and lock
contention, because that division lives inside the process.

## What this has NOT proven
- It does NOT identify the internal cause of the N=3 stall. The tap emits no
  per-batch timing at default settings, so the split between retention sweep, ASR,
  and lock/scheduling contention is unmeasured. Distinguishing them needs the
  bounded internal timing instrumentation (the opt-in startup-diagnostics slice in
  the uncommitted work/ directory, or an equivalent).
- It does NOT prove sustained reliability or a fix; no code was changed during
  measurement.
- It does NOT show GPU capacity pressure: VRAM high-water never exceeded 53.1%.
- It does NOT establish the cause of the 106 s outlier specifically.
- The N=2 window boundary caught one trip line at 22:33:57 that belongs to the
  N=3 transition; treat N=2 as zero-trips-with-caveat and N=3 as the trip rung.

## Evidence files (all in this directory)
metrics-N1.csv, latency-N1.csv · metrics-N2.csv, latency-N2.csv ·
metrics-N3.csv (original gate run), metrics-N3b.csv, latency-N3b.csv ·
gate-trips-N1.jsonl / -N2.jsonl / -N3.jsonl / -N3b-window.json ·
rung-comparison.json · onair-state.json · sample_metrics.py · measure_latency.py ·
commit_chain.py / commit_first.py / package_assets.py / upload_samples3.py (the
sanctioned API calls used to program the channels).

## Boundaries observed
No caption-code changes during measurement. No deletions. No repins. No
ffmpeg/GStreamer/caption-runtime edits. No publish/tag/merge. No CPU substitution.
No unrelated GPU workloads killed.
