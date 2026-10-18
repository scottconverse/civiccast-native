# Preparation and encoder selection

Cold preparation copies compatible H.264 source video while continuing to
prepare its audio. Compatibility requires progressive, square-pixel, 8-bit
YUV 4:2:0 video matching the channel's width, height and frame rate, without
rotation. Unknown metadata, a different format or an accurate nonzero inpoint
keeps the existing video encoding and filtering path. Copy preserves the
source video's GOP and bitrate; the persistent broadcast encoder still
applies the channel's outgoing profile. Loudness processing remains active,
including the audio ride's final mux. Compatibility results are cached against
the source path, size and modification time, with at most 512 entries.

Upcoming-plan preparation runs ahead of queued opportunistic background
warming. Jobs remain FIFO within each priority, with one worker and the
existing per-asset deduplication. A job already running is not interrupted.
After a failed attempt, the asset becomes eligible on the next scheduling
pass after 60 seconds, doubling after consecutive failures up to 30 minutes.
A populated cache resets the failure count; cancellation does not count as a
failure. There is no retry timer that can repeatedly launch an unused asset.
Warnings show the actual delay instead of the old six-hour suppression.

For the native GStreamer output, `canonical_profile.video_codec: h264` means
automatic hardware selection: NVIDIA (`nvh264enc`), then Windows Media
Foundation hardware (`mfh264enc`). If neither is available, automatic H.264
continues using OpenH264 on the CPU, preserving existing CPU-only stations.
An explicit hardware codec name pins that choice; its existing refusal and
**Allow software (CPU) encoding fallback** rules still apply. `libx264`
continues to select the existing OpenH264 software mapping. HEVC rules are
unchanged. Selection applies when starting/restarting the worker, not by
changing an active worker in place.

FFmpeg preparation already resolves declarative H.264 against the exact
binary, with a real one-frame usability check and hardware-first policy.
This work reuses that selector; no second preparation encoder resolver was
introduced.

## Verification — development source, October 17, 2026

Candidate base: `b6f7f6f3`, with the changes in the current working tree.
No installed station, package, broadcast-load or physical-GPU claim.

- Baseline: `.venv/Scripts/python.exe -m pytest tests/egress/test_encoder_decision.py tests/egress/test_preparer.py -q --tb=short`
  returned `133 passed in 7.81s`.
- Focused RED: the six new selected cases returned
  `6 failed, 133 deselected in 2.15s`. Five failed the intended assertions:
  hardware selection (two), fallback refusal, cold copy and recovery delay.
  The queue case failed because the original scheduler put unorderable
  functions into the test's priority queue; that case is not counted as an
  assertion-sensitive RED.
- Focused GREEN: the same selection returned
  `6 passed, 133 deselected in 1.81s`.
- Expanded verification caught an accidental video-copy keyword forwarded
  to the audio leveler. One attempted scripted removal did not remove it;
  direct correction was followed by
  `3 passed, 122 deselected in 1.88s` for the affected normalization/ride paths.
  No audio-leveler interface was changed.
- A requested nonexistent `tests/egress/test_loudness_ride.py` resulted in
  `no tests ran in 0.18s`; the existing window test module was used instead.
- Final affected command:
  `.venv/Scripts/python.exe -m pytest tests/egress/test_preparer.py tests/egress/test_preparer_warm_plan.py tests/egress/test_encoder_decision.py tests/egress/test_loudness_ride_window.py tests/stream/test_ffmpeg.py -q --tb=short`
  returned `255 passed in 11.47s`.
- Native worker integration selection:
  `.venv/Scripts/python.exe -m pytest tests/egress/test_gst_strategy.py -q -k 'preflight or encoder' --tb=short`
  returned `7 passed, 79 deselected in 3.09s`.
- Parent integration review identified that applying explicit-hardware refusal
  to automatic H.264 would break existing default CPU-only channels. The new
  regression returned `1 failed, 13 deselected in 1.73s`, then automatic H.264
  was corrected to retain its existing CPU option. Explicit hardware requests
  still require fallback opt-in. Final command:
  `.venv/Scripts/python.exe -m pytest tests/egress/test_encoder_decision.py -q --tb=short`
  returned `14 passed in 1.53s`; changed selector lint passed.
- Independent integration review identified a foreground/background cache
  eviction race. Its deterministic regression reproduced the `KeyError` with
  `1 failed, 127 deselected in 2.13s`. Cache lookups and writes now use a
  dedicated lock, probing stays outside it, and callers return their own
  decision. The focused copy selection returned
  `4 passed, 124 deselected in 1.66s`.
- Independent review also found that an asset already queued opportunistically
  was deduplicated before it could become upcoming work. A focused regression
  returned `1 failed, 128 deselected in 1.97s`; existing queued jobs can now
  be promoted under the queue lock without duplicating or preempting work.
  The first correction tagged the cache-copy job but missed the conform job;
  the focused run exposed that, and both are tagged now. Queue promotion and
  copy-cache checks then returned `3 passed, 126 deselected in 1.56s`.
- Actual media:
  `.venv/Scripts/python.exe -m pytest tests/egress/test_preparer_conform_cache_real_ffmpeg.py -q -k compatible_cold --tb=short`
  returned `1 passed, 4 deselected in 3.21s`. A real eight-second, 120-frame
  H.264/AAC asset went through cold SourcePreparer processing with video copy;
  every decoded video frame hash matched the original. The fixture selected
  the measured source loudness as its channel target; audio normalization
  preservation is covered separately by the argument/data-path checks.
  Two earlier fixture corrections removed an invalid `None` target and
  distinguished the loudness probe arguments from video-output arguments.

Limits: priority does not preempt active work or continuously reorder equal
priority plans by airtime; retry occurs when scheduling requests the asset
again. Compatibility is metadata-based and intentionally conservative.
Automatic GPU policy was checked with deterministic hardware probes, not a
new physical GPU session. The real media proof covers video preservation and
audio encoding, not a new long-duration loudness or broadcast-load claim.

Scoped Python lint and formatting passed after the final corrections.
Receipt: `proved: affected checks and focused concurrency/promotion regressions
above passed · lane: Critical` (concurrent preparation scheduling).
