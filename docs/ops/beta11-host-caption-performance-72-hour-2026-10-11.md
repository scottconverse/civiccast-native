# Beta 11 host caption station: 72-hour measurement

**Window:** 2026-10-08 14:14:47 MDT through 2026-10-11 14:14:47 MDT

**Service:** CivicCastSupervisor PID 6208; application PID 5388

**Result:** 99.78% retained input coverage across the three monitored channels, based on recorded discard intervals.

## Input coverage

The 72-hour interval represents 777,600 nominal channel-seconds (72 hours × 3 channels). Recorded input discards were:

| Channel | Batches | Discarded seconds |
| --- | ---: | ---: |
| Public | 19 | 575 |
| Government | 17 | 555 |
| Education | 17 | 565 |
| **Total** | **53** | **1,695** |

That leaves 775,905 retained channel-seconds, or **99.7820216% (99.78%)**. This is input coverage from logged discard intervals; it does not measure transcript word accuracy or prove caption timing/availability at every instant.

## Caption and checkpoint observations

There were 216 scheduled checkpoints in the 72-hour window. All 216 completed with healthy service status and all three checkpoint JSON records reported nonzero active VTT cues. The database counts for caption_review_items and offline_caption_jobs were zero at the 216-checkpoint summary.

Caption verdicts were 209 OK and 7 one-channel CAPTION_QUIET observations. Two corresponding samples were silent; five had measurable audio, so those five quiet observations remain visible in the result. The 216 verify-exit.txt values were 1, while the aggregate loudness verifier remained UNVERIFIED because its observed 8-second sample was shorter than the 120-second minimum.

Live A/V checks had numeric offset values in 646 of 648 channel rows. The other two rows still reported ok and listed audio and video, but their offset was n/a: Education at checkpoint 20261010-144707 and Public at 20261011-134702.

The station had three primary Whistle failures during the window, one per channel; all three channels used Whisper fallback. Logged failed Whisper attempts totaled 86: 60 bad-allocation failures and 26 isolated child-deadline timeouts (Public 24, Government 26, Education 36). Per-channel caption scan failures totaled 101, and whole-scan errors totaled 8.

## Host resource observations

The nearest checkpoint before the exact 72-hour endpoint was 2026-10-11 14:07 MDT, 7 minutes 46 seconds before the endpoint. It showed the supervisor and application still running, 4.94 GiB host RAM free, and 342.16 GiB free on C:. The sampled process filter (python, gst, ffmpeg, ollama, postgres) totaled 4.52 GiB working set and 7.03 GiB private bytes. That is a host-wide process sample, not station-attributable memory: a separate 9 GiB Sandbox upgrade-verification guest was active during this checkpoint.

The latest completed snapshot, 2026-10-11 15:27 MDT (about 73 hours 12 minutes after service start), still showed supervisor PID 6208 and application PID 5388 healthy. It reported 13.83 GiB host RAM free and 409.86 GiB free on C:. The same broad process filter totaled 3.92 GiB working set and 7.32 GiB private bytes. These host-wide values are snapshots, not an isolated station memory trend.

## Later current totals

After the 72-hour cutoff and through the 15:27 checkpoint, two additional discard records added 25 seconds: Education 10 seconds and Public 15 seconds. Cumulative current totals were Public 20 batches/590 seconds, Government 17/555 seconds, and Education 18/575 seconds: **55 batches/1,720 seconds**. The 99.78% headline above uses the exact 72-hour window only.

## Evidence pointers

- Existing 48-hour report: C:\Dev\Claude\civiccast-beta11-whistle\docs\ops\beta11-host-caption-performance-48-hour-2026-10-10.md
- Existing 67.5-hour status and summary: C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\HOST-STATION-STATUS-2026-10-11-0946.md and .json
- Observer evidence root: C:\Users\scott\Documents\Codex\2026-10-04\rea\work\station-observer
- Nearest pre-cutoff checkpoint: 20261011-140659; latest checkpoint: 20261011-152701

No repository files or station settings were changed for this report. The exact 72-hour resource reading is the preceding scheduled checkpoint; interval discard counts were cut at the exact endpoint.
