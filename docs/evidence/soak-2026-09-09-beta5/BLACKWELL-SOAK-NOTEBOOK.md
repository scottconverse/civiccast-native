# SOAK state — CivicCast (Native) 1.0.0-beta.5 overnight soak on NvideaBlackwell

Owner spec received 2026-09-09 22:55 MDT (Scott). Runner: Claude session "code-a4" + a detached Python sampler on the machine.
This file is the durable record; chat dies with the session. Update it at every phase change.

## Fixed parameters (from the spec)
- Live captions: ON via Station Profile > "Show live captions on air"; restart each channel after changing it.
- Length: 8 hours from channels On air, or until the owner says stop.
- Output: headend preset "Generic CBR SPTS over UDP" per channel; destinations udp://127.0.0.1:5000 Public, :5001 Government, :5002 Education.
- Clips: all four from C:\Users\scott\Desktop\CivicCast-beta5-kit-148c8d21\samples\ (17.8 MB, 3.8 MB, 34.5 MB, 858.8 MB).
- Schedule: back-to-back 5-minute programs on all three channels covering 9 hours, clips mixed.
- Sampling: every 5 min per channel -> C:\Users\scott\Desktop\SOAK-samples.csv; events -> C:\Users\scott\Desktop\SOAK-events.log.
- Never put passwords or recovery codes in any file. The staff token is passed to the sampler as an environment variable only.
- Do not install/uninstall/reboot/delete; no settings beyond captions + presets.

## Phase log
- 22:56 Prep: API endpoints mapped (upload = POST /api/staff/assets/upload; programs = POST /api/staff/programlog/slots; preset = POST /api/staff/egress/channels/{id}/config/headend-profile with profile "generic-udp-spts"; start/stop = POST /api/staff/egress/channels/{id}/commands {action}; captions = PUT /api/staff/station/profile {live_captions_enabled}).
- 22:56 BLOCKED on sign-in: the browser pane was closed between tasks and the console token with it. Sign-in form is on screen with username filled; owner types the password. Nothing else can start until then.

## Files
- C:\Users\scott\Desktop\SOAK-sampler.py — sampler (5-min CSV rows, 5-s now/next polling for program-change timing, hourly 2-min HLS stall watch, process RSS, alerts, readiness)
- C:\Users\scott\Desktop\SOAK-samples.csv, SOAK-events.log, SOAK-raw.jsonl, SOAK-sampler.log
- C:\Users\scott\Desktop\SOAK-STOP — create this file to make the sampler exit cleanly
- C:\Users\scott\Desktop\SOAK-evidence\ and SOAK-REPORT.md at the end; zip beside them
- 23:04 Token: minted via `civiccast token issue` (token id st15269d4d3ed664f28e6cc5e3, operator soak-runner, scopes admin). Secret lives only in the session and the sampler's environment. REVOKE at the end: `civiccast token revoke st15269d4d3ed664f28e6cc5e3`.
- 23:06 Captions ON via Station Profile UI (PUT /api/staff/station/profile 200, live_captions_enabled=true).
- 23:09 Uploads: all four clips validated in 9 s total (A soak-podcast-360p 67 s; B soak-podcast-1080p 67 s; C soak-weather-360p 667 s; D soak-michelle-1080p 2365 s). The 858 MB clip took 7 s, not minutes.
- 23:10 Schedule: 108 x 5-min 'once' program slots per channel from 23:20 to 08:15 (rotations weighted to the long clips); materialized; committed to air one by one (POST /api/staff/playout/commit). 8 Public slots first collided with my earlier walkthrough premiere (cancelled) and were replaced. Result: 108 published per channel.
- 23:14 Presets: generic-udp-spts applied, udp://127.0.0.1:5000 Public / 5001 Government / 5002 Education (single udp-ts sink each; no HLS sink, so the freeze watch reads the UDP stream, not HLS).
- 23:14:29 All three channels ON_AIR within 11 s of the start command (pids public 23528, government 5228, education 28240), on slate until 23:20.
- 23:16:36 Sampler running detached (pid 2900; python -u SOAK-sampler.py; stdout -> SOAK-sampler.out). Binds UDP 5000/5001/5002 itself to measure feed gaps (VLC cannot bind those ports while it runs).
- 23:17 Early findings BEFORE the first program: Public relaunched twice (23:15:15, 23:16:01) and Government twice (23:15:42, 23:16:28) on the same worker stall ("no output for 10s" after ~3779 buffers on slate); Education stable. Caption tap overload warnings paused live captions 120 s on Public and Government within a minute of start. Public/Government sit in FALLBACK_SLATE, Education in ON_AIR, all on slate until 23:20.
- Worker RSS at first sample: ~830-855 MB per channel worker (python.exe), control plane 470 MB.
- 23:18 Readiness record captured -> C:\Users\scott\Desktop\SOAK-evidence\readiness-start.txt (page text; screenshots live in the runner session). Readiness banner says "Idle / no channels configured for 24/7 automation" while three workers run — misleading wording, noted for the report.
- 23:19 Monitors armed in the runner session: event monitor on SOAK-events.log (RELAUNCH/MISSED/FREEZE/STATE/ALERT/RSS lines), hourly check cron at :23 (job 42070dd6), end-of-soak one-shot 07:20 (job 68c6698f). These die with the session; the sampler does NOT.

## If the runner session dies (resume recipe for any agent)
1. Two detached processes keep running without this session: the sampler (pid 2900, python -u C:\Users\scott\Desktop\SOAK-sampler.py) keeps writing SOAK-samples.csv / SOAK-events.log / SOAK-udp.log until 07:35 or until C:\Users\scott\Desktop\SOAK-STOP exists. Check it with: Get-Process -Id 2900.
2. A new staff token can be minted without a password: from "C:\Program Files\CivicCast (Native)\runtime\python.exe", set DATABASE_URL in-process from GET http://127.0.0.1:8000/api/setup/storage (never write it), then `civiccast token issue --operator-id soak-runner-2 --display-name "soak" --scopes admin --json`.
3. At 07:20: create SOAK-STOP; POST /api/staff/egress/channels/{public,government,education}/commands {"action":"stop"}; copy C:\ProgramData\CivicCast\logs\control_plane-app.log, control_plane.log, supervisor.log and C:\ProgramData\CivicCast\data\egress\<ch>\logs\gst-worker.{stderr,stdout}.log into SOAK-evidence; write SOAK-REPORT.md (start/end, captions ON, per channel: program changes, relaunches with times, longest no-output gap, RSS start/end, alerts, verdict); zip SOAK-evidence + CSV + report as C:\Users\scott\Desktop\SOAK-2026-09-09-beta5.zip; revoke token st15269d4d3ed664f28e6cc5e3.

## Interim findings, first 45 minutes (23:14 - 00:02). Written durably because chat dies.

The station does NOT hold a stable linear channel. Every failure mode the soak was meant to look for
appeared inside the first hour, on a machine with 31.6 GB RAM, an RTX 5070 Ti, and 9% CPU load.

S-01 BLOCKER - a channel died silently at its first scheduled program change and never came back.
  Education went STOPPED at 23:21:01 and stayed STOPPED for 44 minutes until the runner restarted it
  manually at 00:02. Evidence that this was not a crash and not an operator action:
   - worker exit was clean: WORKER_RESULT {'error': None, 'teardown_clean': True}
   - egress state row: last_error = None
   - control_plane-app.log has NO stop command, NO automation decision, and NO error for education
     anywhere between 23:14:21 (worker start) and 23:21:01 (STOPPED), and nothing after it at all
   - at the 23:20 boundary the automation issued a reload for government and public but NEVER for
     education, one second before education stopped
   - the daemon never retried. A PEG station would have been dark until someone noticed.
  The only alert that fired was rule default:off-air with title=None and detail=None (see S-06).

S-02 BLOCKER - the GStreamer worker stalls and is killed and relaunched every few minutes, forever.
  Pattern in gst-worker.stderr.log: "CTRL preroll: reached PLAYING" -> output buffers climb -> the
  buffer count freezes at the same value twice in a row -> "CTRL stall: no output for 10s - quitting
  for daemon restart" -> WORKER_RESULT error=('stall','output stalled') -> daemon relaunches with a
  new pid. Confirmed on slate AND on real program content. Relaunches recorded up to 00:01:
    public:     23:15:15, 23:16:01, 23:19:04, 23:35:13, 23:45:09, 00:01:20 (+ more; pid chain
                23528 -> 6968 -> 27908 -> 13244 -> 29632 -> 24476 -> 28348 -> ...)
    government: 23:15:42, 23:16:28, 23:17:13, 23:19:46, 23:35:24, 23:45:14 (pid chain
                5228 -> ... -> 4360 -> 30384 -> 26364 -> 5884 -> 2472 -> 19792 -> 27960)
    education:  none while it was running (it died instead, S-01)
  Each relaunch takes the channel off air into FALLBACK_SLATE or STARTING for 5-30 s.

S-03 BLOCKER - scheduled program changes do not happen at their boundaries.
  108 five-minute premieres per channel were published and committed to air. At EVERY 5-minute
  boundary from 23:20 to 00:00 the sampler recorded "MISSED program change ... no change within 30 s
  of the boundary" on all three channels. Content does change, but only when a worker relaunch
  happens to reload the plan, so what is on air has no relationship to the published schedule.
  The 23:20 boundary itself: automation issued the reload on time (23:20:01), then
   - "Content-reload source preparation for government took 35.0s for 3 segment(s) (synchronous on
     the automation thread)" and for public 16.3 s - the reload blocks the automation thread
   - "worker command ... lost-ack -> reissue_desired_state" then "Seamless content-reload declined
     for government (ack timeout after 5.0s); falling back to restart"
  So the seamless reload path times out and degrades to a full restart, on the very first change.

S-04 MAJOR - the UDP output to the headend goes silent for 5 to 61 seconds at every relaunch.
  Measured by binding 127.0.0.1:5000/5001/5002 directly. Longest gaps so far: government 61.5 s
  (ending 23:21:19), public 31.4 s (23:21:31), government 15.4 s, public 21.4 s, public 14.8 s,
  public 14.4 s, government 11.9 s, government 11.5 s, public 5.6 s.
  Bitrate is healthy once real content is playing: 1283-5243 kbps measured on public and government
  at 00:00-00:01. (An earlier note in this file said ~260 kbps; that reading was taken while both
  channels were on SLATE and was wrong as a steady-state figure. Corrected here.)
  Education's UDP port was silent for 2497 s continuously - the S-01 outage seen from the wire.

S-05 MAJOR - live captions pause themselves under overload within a minute of going on air.
  "Caption tap overload for channel public: 6 settled segments exceeds the maximum 2. Live captions
  are PAUSED for 120s (overload #1) so playout keeps the CPU" at 23:15:04; government at 23:15:29;
  government again at 23:20:21 with "PAUSED for 240s (overload #2)". Caption status has stayed
  "not-verified" on all three channels for the whole run. With captions ON - the configuration this
  soak was told to test - the station cannot keep captions running on three channels.

S-06 MAJOR - the only alert that fired is unreadable and does not name the channel.
  /api/staff/alert-events?state=firing returns rule_id "default:off-air" with title None and
  detail None. An operator gets a nameless alert for a dark channel.

S-07 MINOR - System Health says "Idle - no channels are configured for 24/7 automation" and
  "0 CRITICAL 0 WARNING" while three channels are running and one of them is dead.

Sampler note: "MISSED program change" is measured against the wall-clock 5-minute boundary using the
egress state's current_source_label, which is the operator-visible source. It is a real miss.

## 00:35 — S-01 REPRODUCED, and the mechanism is now identified. This is the headline finding.

Education died a SECOND time at 00:30:14, 28 minutes after the runner restarted it at 00:02.
Same shape as the first death: state -> STOPPED, no relaunch, no recovery, dark until a human acts.
The runner restarted it again at 00:31:59 (ON_AIR 00:32:05, third life). Deaths so far: 23:21:01, 00:30:14.

S-08 BLOCKER (root cause of S-01) — a seamless content-reload can commit a HALF-BUILT pipeline,
and the worker's clean exit is then read by the daemon as "the operator wanted this channel off".

  Evidence, all from the product's own logs:
  1. Every healthy seamless reload on this box commits 146 elements. Count across all three
     channels for the whole run: public 4x146, government 5x146, education 2x146 — and exactly ONE
     outlier, education's 00:30:12 reload, which committed elements=56. That single 56-element
     reload is the one that killed the channel.
  2. The healthy reload sequence in gst-worker.stdout.log is:
        switching selector -> new leg stream held at its first buffer (1 stream(s) still to preroll)
        -> ... (0 stream(s) still to preroll) -> boundary switch rebased to running time N
        -> switching selector -> old leg disposed -> holds released -> committed (elements=146)
     The fatal sequence skipped every preroll line:
        switching selector -> old leg disposed -> holds released -> committed (elements=56)
     The old leg was disposed before the new leg had prerolled. The pipeline that got committed was
     missing ~90 elements. gst-worker.stderr.log shows the output counter jump 91655 -> 102316 in a
     single tick (normal tick is +380..+460) as the old leg was dumped, then the file simply ends.
  3. The worker then exited with WORKER_RESULT {'error': None, 'teardown_clean': True} — a CLEAN exit.
     Public and government workers exit with {'error': ('stall','output stalled')} and are relaunched
     every time. Education exits with error=None and is never relaunched. Both of education's deaths
     have error=None; those are the only two error=None exits in the whole run.
     So the recovery rule appears to be "relaunch on error, respect a clean exit" — which means the
     one failure mode that produces a clean exit is the one failure mode with no recovery.
  4. Nothing else exists to diagnose it with: no WARNING, no ERROR, no stop command and no automation
     decision in control_plane-app.log for education after the reload; egress last_error = None; and
     no Windows Application/WER crash record at 00:30 (checked). The process is simply gone.
  5. Caption tap overload fired for education 6 seconds before the fatal reload committed:
     "20 settled segments exceeds the maximum 2 ... Live captions are PAUSED for 120s (overload #1)".
     20 settled segments is by far the largest backlog seen this run (others were 6). Captions ON is
     the configuration under test, so this is a plausible contributor and should be tested both ways.

  Why this is a BLOCKER for a PEG station: the channel goes to black, the daemon believes it is
  supposed to be off, and nothing brings it back. First outage was 44 minutes and only ended because
  the runner intervened. Unattended overnight, it is dark until morning.

S-06 UPDATE — the off-air alert did fire this time, at 00:31:48, about 94 seconds after the channel
  died. It is still rule default:off-air with title=None and detail=None and still does not name
  education. On the first death the same nameless alert was the only signal. So: the alert exists,
  it is roughly 90 s late, and it does not tell the operator which channel is dark.

S-09 MAJOR (new) — a real media read failure on public, silently absorbed. public's worker exited with
  gerror "Internal data stream error." / gstbasesrc.c(3187) gst_base_src_loop(): filesrc3
  "streaming stopped, reason error (-5)", followed by "CTRL reload aborted: new program errored
  before commit (source=filesrc9)". A source file failed to read mid-programme. Nothing about this
  reached the operator UI, the alerts feed, or last_error; it looks like just another relaunch.

## 00:36 — S-08 is NOT education-specific. Public died the same way five minutes later.

Public went STOPPED at 00:35:14 with the identical signature: automation issued the 00:35 reload on
time, "Seamless content-reload armed for public", then in gst-worker.stdout.log
"switching selector -> old leg disposed -> holds released -> committed (elements=56)" with none of the
preroll-hold lines, then WORKER_RESULT {'error': None, 'teardown_clean': True} and no relaunch.
Public's element histogram is now 4x146 and 1x56 — again, the single 56-element reload is the one that
killed it. Runner restarted public at 00:35:39 (ON_AIR 00:35:46).

Deaths so far: education 23:21:01, education 00:30:14, public 00:35:14. Three silent deaths in 81
minutes across two of the three channels, each needing a human to bring the channel back.

Caption-overload correlation (the setting this soak was told to run with is captions ON):
  Twelve "Caption tap overload" warnings so far. Ten are small (3-7 settled segments) and the channel
  survives. The two large ones are each followed within seconds by the fatal 56-element reload:
    00:30:08 education, 20 settled segments -> 00:30:12 reload elements=56 -> dead 00:30:14
    00:35:07 public,    17 settled segments -> 00:35:12 reload elements=56 -> dead 00:35:14
  The 23:21 education death has no caption overload near it, so captions are not the sole trigger, but
  a caption backlog of 17-20 segments looks like a marker of the same resource stall that makes the new
  pipeline leg miss its preroll window. Worth the coder testing the reload path with captions OFF.
  NOTE: captions were deliberately left ON — the owner's spec names captions ON as the configuration
  under test and forbids changing settings, so this run does not flip it.

Also at 00:35:05, on government: "Seamless content-reload for government did not land
(aborted:stopped); falling back to restart." Same reload wave, third outcome — three channels, three
different results from one scheduled program change.

## 00:37 — operator watchdog added (runner's own decision, recorded here for the report)

Three silent deaths in 81 minutes, and the daemon never recovers from any of them. Without something
pressing Start, all three channels would likely be dark within a couple of hours and the remaining six
hours of the soak would measure nothing. So the runner started a detached watchdog:

  C:\Users\scott\Desktop\SOAK-watchdog.py  (pid 30792, python -u, token from the environment only)
  - polls each channel's egress state every 10 s
  - if a channel has been STOPPED for 120 s continuously, issues exactly one start command
  - changes NO station setting and issues no other command; it is a stand-in for a human operator
  - writes every observed death and every restart, with timestamps and how long the channel was dark,
    to C:\Users\scott\Desktop\SOAK-interventions.log
  - exits when SOAK-STOP exists or after 7.2 h

Effect on the measurements, stated plainly so the report is honest: from 00:37 onward, "longest gap
with nothing on air" is capped at roughly 120-135 s by the watchdog, EXCEPT for the three deaths
before it existed (education 44 min at 23:21, education ~2 min at 00:30, public ~30 s at 00:35 —
the last two were short only because the runner was watching live). The uncapped, true-to-life number
is the 44-minute one: that is what an unattended station gets. The count of deaths, their timestamps,
and every log signature remain untouched by the watchdog.

Manual restarts by the runner before the watchdog existed: education 00:02, education 00:31:59,
public 00:35:39. All three are in the phase log above.

Resume-recipe addendum: the watchdog (pid 30792, SOAK-watchdog.py) also survives this session and
needs CIVICCAST_STAFF_TOKEN in its environment; if it has died, relaunch it the same way or restart
stopped channels by hand. Check both: Get-Process -Id 2900,30792.

## 00:53 — fourth death (public, 00:51:52), and two new facts that sharpen S-08 and S-03

S-08 refined: the fatal signature is not the number 56, it is "a reload that commits FEWER elements
than a healthy one". Public's histogram is now 5x146, 1x56, 1x74. The 74-element commit at 00:51:52
killed it exactly like the 56-element one did, with the same missing preroll lines
("switching selector -> old leg disposed -> holds released -> committed") and the same clean
WORKER_RESULT {'error': None, 'teardown_clean': True}. Healthy reloads are always 146 and always show
"new leg stream held at its first buffer (N stream(s) still to preroll)" first. So: if the new leg has
not prerolled when the old leg is disposed, the commit is short and the worker quietly dies.

S-10 BLOCKER (new) - this death was completely invisible to the control plane. Between 00:49 and
  00:53 the ENTIRE control_plane-app.log contains exactly one line about public: the STOPPED state
  row. No automation decision, no "Seamless content-reload armed", no warning, no error. The worker
  performed a program reload and died from it, and the service that supervises it logged nothing.
  The likely source of that unlogged reload: at 00:39:10 a reload was armed for public with
  "switch_at_end_of_current=True" covering 12 segment(s). A deferred reload of that kind lands
  whenever the current item ends - here about 12 minutes later - with no log line when it actually
  fires. Deferred reloads are therefore both unobservable and, in this build, lethal.

S-11 BLOCKER (new) - the automation loop has started skipping scheduled boundaries outright.
  Last "Channel automation issued reload" of any kind: 00:45:00 (government and public). The 00:50
  boundary produced NO reload for any of the three channels, and none had been issued by 00:52.
  Earlier in the run automation at least issued the reload and the reload then failed to land (S-03);
  now it is not issuing them at all. Combined with the repeated note that source preparation runs
  "synchronous on the automation thread" (35.0 s at 23:20), this looks like the single automation
  thread getting further and further behind until boundaries are simply dropped.
  Consequence for a PEG station: the published schedule and what is on the cable have fully diverged.

Watchdog behaved as designed on its first real test: observed public STOPPED at 00:51:57, held for the
120 s grace, restart to follow. Interventions are in SOAK-interventions.log.

## 01:06 — all three channels have now died the same way. S-08 is universal.

Government STOPPED at 01:05:18: "switching selector -> old leg disposed -> holds released ->
committed (elements=56)" with no preroll-hold lines, then WORKER_RESULT {'error': None,
'teardown_clean': True}, then STOPPED with no relaunch. Histogram 7x146 + 1x56.

Running tally of silent deaths (S-08), all with an undersized reload commit and a clean error=None exit:
  23:21:01 education   (dark 44 min; runner restarted 00:02)
  00:30:14 education   (runner restarted 00:31:59)
  00:35:14 public      (runner restarted 00:35:39)
  00:51:52 public      (watchdog restarted 00:54:01; 138.2 s dead air measured on the wire)
  01:05:18 government  (watchdog to restart)
Five deaths in 111 minutes, across all three channels. Every one required an operator to press Start;
in no case did the station recover by itself. Undersized commits seen: 56 (x4) and 74 (x1) against a
healthy 146 every time.

From here the runner stops writing a separate note per death - the mechanism is established and the
sampler, the events log and SOAK-interventions.log capture each one. The hourly summaries carry the
counts, and the end-of-soak report will carry the full table.

## Hourly

### Hour 2 summary — 2026-09-10 01:30 MDT (soak started 23:14, elapsed 2 h 16 m)

State right now: all three channels ON_AIR and on the wire — public 1045 kbps, government 5058 kbps,
education 2160 kbps, no UDP gap over 0.08 s in the last minute. Sampler (pid 2900) and watchdog
(pid 30792) both alive. 82 CSV rows written.

Totals since 23:14:
  silent deaths (S-08):     5   — public 2, education 2, government 1; all three channels affected
  worker relaunches (S-02): 12  — government 7, public 4, education 0
  missed program changes:   57  — education 21, public 18, government 18. Not one scheduled
                                  5-minute boundary has changed programme on time all night.
  UDP freezes over 5 s:     31  — longest 2498.9 s (the 44-min education outage), then 146.2 s,
                                  138.2 s, 117.3 s, 61.5 s
  alerts fired:             3   — all rule default:off-air, all with title=None and detail=None
  operator restarts:        5   — 3 by the runner by hand, 2 by the watchdog (124 s dark each)

S-12 MAJOR (new, found during this check) — caption verification is FAILING, and the UI does not say so.
  GET /api/staff/egress/channels/<ch>/caption-status returns, for all three channels:
    status "FAIL", caption_status "not-verified", expected_cue_count 0, decoded_cue_count 0,
    matched_cue_count 0, blocker "EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES",
    proof_boundary "egress-caption-embed-to-emitted-stream-decode-back", decoder ffmpeg-subcc, mode cea-708
  So with live captions ON, zero CEA-708 cues are reaching the emitted transport stream, and the
  decode-back proof fails. The operator-facing wording is the soft "Not yet confirmed (waiting for the
  on-air check)" — a hard FAIL is being shown as "not yet checked".
  Worse: sampled_at is 05:15-05:16 UTC (23:15-23:16 MDT) on all three channels. The caption check ran
  ONCE, about a minute after the channels came up, and has not run again in over two hours. sample_id
  is 4. So the number an operator sees is both wrong in tone and two hours stale.

S-13 MINOR (new) — RSS is climbing on the two long-lived processes.
  pythonservice.exe (supervisor, pid 15844): 35.0 MB at 23:16 -> 77.4 MB at 01:26. It has more than
  doubled in two hours with no channel work of its own to do.
  control plane python.exe (pid 5172): 469.7 -> 534.6 MB (+65 MB in two hours).
  The egress workers cannot be trended because S-08/S-02 keep replacing them; a fresh worker sits at
  about 500 MB and the longest-lived one currently reads 886.7 MB.
  Nothing here is fatal in one night, but neither line is flat, and a PEG station runs for months.

Note for whoever reads the CSV: the rss_mb_by_process column from 00:37 onward also lists
python.exe pid 30792 at about 22 MB. That is the runner's own watchdog, not a station process.

## 07:35 — SOAK CLOSED

Sampler reached its 8.3 h window and exited on its own at 07:34:36. Runner then:
  - created SOAK-STOP (watchdog exited 07:35:30; restarts issued public=5, government=6, education=5)
  - stopped all three channels (all confirmed state STOPPED)
  - copied control_plane-app.log, control_plane.log, supervisor.log and the per-channel
    gst-worker.stdout/stderr logs into SOAK-evidence, plus the three scripts and the readiness record
  - wrote SOAK-REPORT.md
  - zipped everything to C:\Users\scott\Desktop\SOAK-2026-09-09-beta5.zip
    Final size and SHA-256 are in the handover note in chat and in the memory file civiccast-beta5-soak-2026-09-09.md;
    they cannot be stated here because this file is inside the zip.
  - revoked staff token st15269d4d3ed664f28e6cc5e3 (verified: the token now returns HTTP 401)

Final totals, 23:14 -> 07:35 (8 h 21 m): 19 silent channel deaths, 0 self-recoveries, 19 restarts from
outside the product, 218 missed programme changes out of ~300, 0 on-time programme changes, 67 worker
exits, 118 feed interruptions over 5 s, longest unattended dark period 41 m 39 s, 14 alerts all
nameless, captions FAIL on all three channels. Verdict: this build cannot run an unattended channel.

State left on the machine: three channels stopped with the soak schedule (108 published 5-minute
programmes each, 23:20-08:15) and the generic-udp-spts headend preset still configured; four soak
clips still in the asset library; live captions still ON in Station Profile. Nothing was uninstalled,
deleted, or otherwise changed.

## 07:45 — late cron jobs fired (hourly + end-of-soak); reconciled

The :23 hourly and the 07:20 end-of-soak one-shot both fired after the run had already been closed out
at 07:35. Nothing was re-run against the station: channels stay stopped, no settings touched, no
deletions. Two gaps in the earlier close-out were filled from the end-of-soak checklist:
SOAK-raw.jsonl (363 KB) and SOAK-sampler.out (163 KB, the sampler's own stdout - the spec calls it
SOAK-sampler.log) were added to SOAK-evidence and the zip rebuilt.
  C:\Users\scott\Desktop\SOAK-2026-09-09-beta5.zip
  Final size and SHA-256 are in the handover note in chat and in the memory file
  civiccast-beta5-soak-2026-09-09.md; they cannot be stated here because this file is inside the zip.
One deviation from the end-of-soak script, recorded for accuracy: the token was revoked at 07:39 with
the CLI's default reason string "operator-requested" rather than "soak-complete". The token
st15269d4d3ed664f28e6cc5e3 is dead either way (verified HTTP 401) and cannot be revoked twice.
