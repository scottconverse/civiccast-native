# Independent verification of the 2026-09-09 beta.5 overnight soaks

Written 2026-09-10 by the coordinating session, after reading both reports end to end and
**re-deriving every headline number from the raw evidence** rather than trusting the summaries.
This note records what held, what did not, and what the evidence does not cover.

Everything below was computed from the two zips in this directory.

## The two runs

| | Blackwell (`blackwell-evidence.zip`) | Clean machine (`clean-evidence.zip`) |
|---|---|---|
| Window | 2026-09-09 23:14 → 2026-09-10 07:35 MDT (8 h 21 m) | 2026-09-10 00:05 → 08:04 MDT (8 h) |
| Captions | **ON** | **OFF** |
| Hardware | Win 11 Pro, 31.6 GB RAM, RTX 5070 Ti, ~9% CPU all night | not stated in the report |
| Output | `generic-udp-spts` → udp://127.0.0.1:5000/5001/5002 | same |
| Schedule | 108 × 5-min programmes per channel | 5-min mixed-clip slots per channel |
| Verdict | "cannot run an unattended cable channel" | "This soak failed." |

## The mechanism, verified

The Blackwell report's root-cause claim (its B-1 / notebook S-08) is **confirmed by direct count**
of `SOAK-evidence/*/gst-worker.stdout.log`:

| Measure | public | government | education | **total** |
|---|---|---|---|---|
| Healthy reload commits (`elements=146`) | 32 | 29 | 29 | **90** |
| Undersized commits (`elements=56` or `74`) | 7 | 7 | 6 | **20** |
| Worker exits `error: None` (clean) | 7 | 6 | 7 | **20** |
| Worker exits `('stall','output stalled')` | 6 | 17 | 6 | 29 |
| Worker exits with a GStreamer `gerror` | 6 | 8 | 4 | 18 |
| **All worker exits** | 19 | 31 | 17 | **67** |

**20 undersized commits ↔ 20 clean exits.** The correspondence is exact.

The log signature is unambiguous. A healthy reload is:

```
CTRL reload: switching selector
CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll)
CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll)
CTRL reload: boundary switch rebased to running time N
CTRL reload: switching selector
CTRL reload: old leg disposed
CTRL reload: holds released
CTRL reload committed (elements=146)
```

A fatal one skips every preroll line:

```
CTRL reload: switching selector
CTRL reload: old leg disposed
CTRL reload: holds released
CTRL reload committed (elements=56)
WORKER_RESULT {'error': None, 'teardown_clean': True}
```

The old leg is disposed before the new leg has prerolled, ~90 elements never get built, the worker
has nothing to play, and it shuts down **tidily**. The daemon relaunches on error but treats a clean
exit as an intentional operator stop — so the single failure mode that produces a clean exit is the
single failure mode with **no recovery**.

## Other headline numbers, re-derived

Computed from `SOAK-events.log`, `SOAK-udp.log`, `SOAK-samples.csv` and `SOAK-raw.jsonl`:

- **218** `MISSED` programme-change lines. **0** on-time changes.
- **117** UDP gap readings over 5 s (report says 118 feed interruptions; the events log carries 118
  `FREEZE` lines — consistent within method). **18** over 100 s.
- Longest gap **2498.9 s** (41 m 39 s), education, ending 00:03:03 — the only outage measured before
  the runner's watchdog existed. Next longest are all ~150-160 s, i.e. watchdog-capped.
- **14** alerts, every one `default:off-air`. Verified in the events log.
- **300** samples. `captions_state` is `not-verified` in **all 300**.
- `last_error` is **empty in all 300 samples** — the deaths really are silent at the API surface.
- `sink_connected` reports `Cable headend: false` in **180 of 300** samples.
- Memory: control plane 469.7 → 573.0 MB; supervisor `pythonservice.exe` 35.0 → 77.7 MB; the
  longest-lived worker reached 1126.5 MB.

## Three claims that do NOT hold

These matter, because the reports are otherwise well evidenced and will be acted on.

**1. Dropped frames — withdraw this finding.**
The Blackwell report's M-5 claims the dropped-frame counter climbed to 312 (public), 876
(government) and 731 (education). **Every `dropped_frames` value in the evidence is `0`** — all 300
raw API samples, and the CSV column, and there is no dropped-frame figure anywhere in
`control_plane-app.log` or any worker `stderr` log. The sampler even contains a rise-detector
(`> p["dropped_frames"]`) and it never fired once. The clean report states the reason plainly:
beta.5 reports 0 when no supported GStreamer drop metric is emitted. **The station's picture
quality between failures is unmeasured, not proven bad.**

**2. Caption overload — badly understated, in the safe direction.**
The report says **12** "Caption tap overload" warnings. The real count in `control_plane-app.log`
is **182**, escalating through overload #1 (120 s pause) to overload #10 (900 s pause):

```
106 × PAUSED for 120s (overload #1)
 31 × PAUSED for 240s (overload #2)
 13 × PAUSED for 480s (overload #3)
 32 × PAUSED for 900s (overload #4..#10)
```

Backlogs reached **38** settled segments, not 20. The "12" was a figure from an interim note at
00:36 that never got refreshed for the final report.

**3. "The automation loop stopped issuing reloads at all" — too broad.**
Automation issued **97** reloads spread evenly across every hour of the run, right through to
07:35:01. It did not stop. But it only ever fires at *some* boundary minutes — `:00 :05 :10 :15 :20
:30 :35 :40 :45` and **never** `:25 :50 :55`. The specific claim that the 00:50 boundary produced no
reload is **true and verified**. The correct statement is: *automation systematically skips roughly
two thirds of scheduled boundaries* (97 reloads against ~300 boundary-channel events), not that it
stopped.

## The clean machine hit the same bug — its own report did not name it

The clean report concludes "no verifiable outgoing worker feed". Its own evidence shows otherwise
and points at the same root cause:

- Worker `stderr` logs show output buffers climbing to **87,319** (education) and **56,184**
  (government). The workers ran and produced output.
- Each then committed **`elements=33`** (4 occurrences) and exited **`WORKER_RESULT {'error': None,
  'teardown_clean': True}`** — the identical silent-death signature, at a different healthy element
  count for that machine's pipeline.
- That is why the console advertised **PIDs 9628 and 9224 for processes that no longer existed**,
  and why all three channels sat frozen for the whole run: Public `FALLBACK_SLATE` ×66 samples,
  Government `TRANSITIONING` ×66, Education `ON_AIR` ×66. Never a single state change in 8 hours.
- **15 × "CTRL reload superseding a still-settling reload"** — reloads stacking faster than they
  settle, which the Blackwell box did not show.
- Public additionally had `last_error = "No valid source plan is available; generated fallback
  slate."` and its schedule never fully committed (`schedule_publication_failure` event at 00:22:32:
  slots from 00:25 showed "Ready to review" rather than "Committed").
- Stop was issued and confirmed in the operator UI at the end; the public status endpoint still
  reported `FALLBACK_SLATE` / `TRANSITIONING` / `ON_AIR`.

**Conclusion: the silent-death bug is not captions-related and not machine-specific.** It reproduced
with captions OFF on different hardware.

## Evidence gaps — stated so nobody assumes coverage

- **The clean machine's `control_plane-app.log` does not cover its own soak.** It runs
  21:08 → 00:02:18, and the soak ran 00:05:14 → 08:04:38. The service-side view of that run is
  missing; only the sampler CSV/events and the worker logs cover it.
- The Blackwell zip's two large service logs (`control_plane-app.log` 7.3 MB,
  `control_plane.log` 4.2 MB) were **queried, not read line by line**, by this verification. Every
  number above comes from a count run over them, not from a summary.
- Both runs used `udp://127.0.0.1` loopback destinations. **No physical cable headend was involved**
  in either soak.
- Blackwell's numbers from 00:37 onward are shaped by the runner's own watchdog
  (`SOAK-watchdog.py`), which restarted a channel after 120 s STOPPED. It issued **16** restarts
  (public 5, government 6, education 5) plus 3 earlier manual restarts. It changed no setting and
  issued no command other than Start. Death counts, timestamps and log signatures are unaffected;
  "longest gap" after 00:37 is capped at ~125 s by the watchdog, not by the product.
