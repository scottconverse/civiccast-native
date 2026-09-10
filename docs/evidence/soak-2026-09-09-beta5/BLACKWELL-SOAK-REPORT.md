# Overnight soak report --- CivicCast (Native) 1.0.0-beta.5

**Machine:** NvideaBlackwell (Windows 11 Pro, 31.6 GB RAM, RTX 5070 Ti,
CPU load around 9% all night) **Ran:** 2026-09-09 23:14 to 2026-09-10
07:35 MDT --- 8 hours 21 minutes **Run by:** Claude (session
\"code-a4\") plus two detached Python processes on the machine
**Settings under test:** live captions ON; headend preset \"Generic CBR
SPTS over UDP\" on all three channels to udp://127.0.0.1:5000 (Public),
:5001 (Government), :5002 (Education); 108 back-to-back five-minute
programmes published per channel, four clips from the beta.5 kit
rotated.

## TL;DR --- the verdict

**This build cannot run an unattended cable channel. It should not ship
to a city.**

In 8 hours and 21 minutes on an idle, over-specified machine, the three
channels went silently dead **19 times**. Not once did the station
recover on its own --- every single recovery required something outside
the product to press Start again. The published schedule and what
actually went out over the cable had essentially no relationship to each
other: of roughly 300 scheduled five-minute programme changes, **218 did
not happen at their scheduled time**. Live captions, the configuration
this soak was told to run, never once verified --- the product\'s own
decode-back proof returned FAIL on all three channels with zero caption
cues found in the outgoing stream, while the operator screen showed the
reassuring \"Not yet confirmed (waiting for the on-air check)\".

The single worst moment is the honest one, because it is the only outage
that happened before anything was babysitting the station: Education
died at 23:21 and stayed black for **44 minutes**, until a human
noticed. Everything after that was rescued within about two minutes by a
watchdog the runner wrote mid-soak. Without it, on the evidence of the
death rate, the station would have been entirely dark before 2 a.m. and
stayed that way until morning.

## What \"went dead\" means, and why it is the headline

Each channel is played out by a separate helper program (a \"worker\")
that builds the video and pushes it to the cable headend. When the
schedule says it is time for the next programme, the service asks that
worker to swap in the new content without interrupting the picture --- a
\"seamless reload\".

A healthy seamless reload always does the same thing, and it is visible
in the product\'s own log: it builds the new video path, **waits for it
to be ready** (\"new leg stream held at its first buffer, N streams
still to preroll\"), and only then throws away the old one and commits
--- **146 elements**, every time.

**20 times last night, the reload skipped the waiting step.** It
disposed of the old video path before the new one was ready and
committed a half-built pipeline --- 56 elements (17 times) or 74
elements (3 times) instead of 146. The worker was then left with nothing
to play, so it shut itself down **cleanly**, reporting error: None.

And that clean report is the second half of the bug. The service
relaunches a worker that dies with an error --- it did that 29 times
last night for ordinary stalls. But a worker that exits *cleanly* is
treated as \"the operator meant to turn this channel off\". So the one
failure mode that produces a clean exit is the one failure mode with
**no recovery at all**. The channel goes to black, the station believes
that is correct, and nothing ever brings it back.

The arithmetic lines up exactly: **20 undersized reload commits → 20
clean error: None worker exits → 19 recorded channel deaths** (the
twentieth was the shutdown at the end of the run).

## The numbers

  -----------------------------------------------------------------------------
  **Measure**        **Public**   **Government**   **Education**      **Total**
  -------------- -------------- ---------------- --------------- --------------
  Silent deaths               6                6               7         **19**
  (channel went                                                  
  dead, no                                                       
  recovery)                                                      

  Restarts                  5+1                6             5+2         **19**
  needed from                                                    
  outside the                                                    
  product                                                        

  Programme                   0                0               0          **0**
  changes that                                                   
  happened on                                                    
  time                                                           

  Missed                     77               72              69        **218**
  programme                                                      
  changes                                                        

  Undersized                  7                7               6         **20**
  reload commits                                                 
  (the fatal                                                     
  ones)                                                          

  Healthy reload             32               29              29             90
  commits                                                        

  Worker exits               19               31              17         **67**
  of all kinds                                                   

  Peak dropped              312              876             731            ---
  frames within                                                  
  one worker\'s                                                  
  life                                                           
  -----------------------------------------------------------------------------

Other totals across the whole run:

- **Feed interruptions over 5 seconds:** 118, measured by listening on
  the UDP ports directly. 18 of them were longer than 100 seconds.

- **Longest period with nothing on air:** **41 minutes 39 seconds**
  (Education, from 23:21). This is the only outage measured before the
  watchdog existed, so it is the only one that shows what an unattended
  station actually gets. After 00:37 every gap was capped at about 125
  seconds by the watchdog, not by the product.

- **Alerts raised:** 14, every one of them the same rule
  default:off-air, and every one with **no title and no detail** and
  **no mention of which channel went dark**. They also arrived roughly
  90 seconds after the fact.

- **Memory:** control plane 469.7 MB → 573.0 MB (+103 MB in 8 h).
  Supervisor service 35.0 MB → 77.7 MB (more than doubled, with no work
  of its own to do). The longest-lived playout worker reached 1,126 MB.
  Nothing here is fatal in one night, but nothing is flat either, and a
  PEG station runs for months between restarts.

- **Samples recorded:** 300 rows in SOAK-samples.csv, one per channel
  every 5 minutes.

## Findings, worst first

**B-1 (blocker) --- a seamless programme change can commit a half-built
video pipeline and silently kill the channel, with no recovery.** 20
occurrences. The reload disposes the old video leg before the new one
has prerolled and commits 56 or 74 elements instead of 146. The worker
exits cleanly with error: None; the daemon reads a clean exit as an
intentional stop and never relaunches. Evidence: gst-worker.stdout.log
per channel --- compare any elements=146 sequence (which contains \"new
leg stream held at its first buffer\") against the elements=56 /
elements=74 ones (which do not). *Fix has two halves: make the reload
refuse to dispose the old leg until the new one has prerolled, and make
the daemon treat \"worker exited while the channel is supposed to be on
air\" as a fault regardless of the exit code.*

**B-2 (blocker) --- scheduled programme changes do not happen.** 218
missed boundaries; zero on-time changes in 8 hours. Content did change
on screen, but only as a side effect of a worker being relaunched, so
what was on the cable had no relationship to the published schedule.
Contributing causes visible in the log: source preparation runs
**synchronously on the automation thread** (35.0 seconds for one channel
at the very first boundary), the seamless reload path times out after 5
seconds (\"ack timeout after 5.0s; falling back to restart\"), and later
in the run the automation loop **stopped issuing reloads at all** ---
the 00:50 boundary produced no reload for any channel.

**B-3 (blocker) --- the station cannot keep a worker alive for long.**
67 worker exits in 8 hours across three channels; 29 of them the same
\"no output for 10 seconds, quitting for daemon restart\" stall. Each
relaunch takes the channel off air for 5 to 60 seconds. This happened on
the slate as well as on real video, so it is not a property of the test
content.

**B-4 (blocker) --- a channel death is invisible to the control plane.**
For the Public death at 00:51:52, the entire service log between 00:49
and 00:53 contains exactly one line about Public: the STOPPED row. No
reload, no warning, no error, no stop command. The reload that killed it
had been armed 12 minutes earlier as a deferred switch
(switch_at_end_of_current=True) and logged nothing when it actually
fired. Deferred reloads are both unobservable and, in this build,
lethal.

**M-1 (major) --- live captions never verified, and the screen
understates it.** The product\'s own check
(/api/staff/egress/channels/\<id\>/caption-status) returned status: FAIL
on all three channels, with expected_cue_count: 0, decoded_cue_count: 0,
and blocker EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES --- meaning zero
caption cues could be read back out of the stream the station was
actually emitting. The operator screen showed the soft \"Not yet
confirmed (waiting for the on-air check)\". Worse, the check ran
**once**, about a minute after the channels came up at 23:15, and never
ran again in the following eight hours. Given captions are an ADA
compliance obligation for this product, a hard FAIL displayed as \"not
yet checked\" is the most dangerous wording in the interface.

**M-2 (major) --- live captions pause themselves under load.** 12
\"Caption tap overload\" warnings, e.g. \"6 settled segments exceeds the
maximum 2. Live captions are PAUSED for 120s (overload #1) so playout
keeps the CPU\" --- the first within 50 seconds of the first channel
going on air. The two largest backlogs of the night (20 and 17 settled
segments) each landed 5-6 seconds before a fatal undersized reload,
which suggests captions contribute to the resource stall behind B-1.
Worth the coder testing the reload path with captions off to confirm.

**M-3 (major) --- the off-air alert is unusable.** All 14 alerts were
rule default:off-air with title: None, detail: None, and no channel
name, arriving about 90 seconds late. An operator gets a nameless
notification and no way to tell which of three channels is dark.

**M-4 (major) --- real media errors are absorbed silently.** A worker
died with GStreamer \"Internal data stream error ... streaming stopped,
reason error (-5)\" on a source file, followed by \"reload aborted: new
program errored before commit\". None of this reached the operator
interface, the alerts feed, or the channel\'s last_error; it looked like
just another relaunch.

**M-5 (major) --- frames are dropped continuously in normal operation.**
The dropped-frame counter climbed to 312 (Public), 876 (Government) and
731 (Education) within individual worker lifetimes, then reset to zero
on each relaunch. The station is not delivering a clean picture even
between failures.

**m-1 (minor) --- memory climbs on every long-lived process.** See the
numbers above.

**m-2 (minor) --- System Health is actively misleading.** It read \"Idle
--- no channels are configured for 24/7 automation\" and \"0 CRITICAL, 0
WARNING\" throughout, including while three channels were running and
one was dead. Readiness also showed \"Cable headend: NOT CONNECTED\" for
a channel that was streaming, and \"CONNECTED\" for one that was not.

## What the runner changed, so the report is honest

Two things were added by the runner during the soak and both affect the
numbers:

1.  **Three manual restarts** (Education 00:02 and 00:31, Public 00:35)
    before any automation existed.

2.  **An operator watchdog** (SOAK-watchdog.py) started at 00:37, which
    restarted a channel after it had been STOPPED for 120 seconds and
    logged every intervention. It issued **16 restarts** (Public 5,
    Government 6, Education 5). It changed no station setting and issued
    no command other than Start.

The watchdog exists because without it the soak would have measured
nothing after about 2 a.m. Its cost to the measurements is that
\"longest gap with nothing on air\" is capped at roughly 125 seconds
from 00:37 onwards. **The uncapped, true-to-life figure is the 41 minute
39 second Education outage at 23:21.** Every death, timestamp and log
signature is unaffected by the watchdog.

Live captions were deliberately left ON for the whole run, per the spec,
even after they became a suspect in B-1.

## Evidence

Everything is in C:\\Users\\scott\\Desktop\\SOAK-2026-09-09-beta5.zip
(the zip\'s own size and SHA-256 are recorded in SOAK-STATE.md\'s
close-out section and in the handover note, since a file inside the
archive cannot state the archive\'s hash):

- SOAK-samples.csv --- 300 rows, one per channel every 5 minutes: state,
  pid, source label, seconds on air, dropped frames, caption state,
  memory per process, readiness banner, alerts, UDP bitrate and worst
  feed gap.

- SOAK-events.log --- every state change, programme change, missed
  boundary, relaunch and feed freeze, timestamped.

- SOAK-udp.log --- per-minute bitrate and worst packet gap on each of
  the three UDP ports, measured by binding the ports directly.

- SOAK-interventions.log --- every death the watchdog saw and every
  restart it issued, with how long the channel was dark.

- SOAK-STATE.md --- the running notebook written during the soak, with
  findings S-01 to S-13 as they were discovered and the raw log excerpts
  behind each one.

- SOAK-raw.jsonl --- the raw API responses behind every sample, if
  anyone wants to re-derive the CSV.

- SOAK-evidence\\ --- control_plane-app.log, control_plane.log,
  supervisor.log, the per-channel gst-worker.stdout.log and
  gst-worker.stderr.log (in public\\, government\\, education\\), the
  start-of-soak readiness record, the sampler\'s own stdout
  (SOAK-sampler.out), and the three scripts used to run and measure the
  soak.

The fastest way for the coder to see B-1: open any
gst-worker.stdout.log, search for elements=56, and compare the four
lines above it with the eight lines above any elements=146.

## Plain verdict

The station played video all night, and when a channel was up the
picture went out at a healthy bitrate --- so the encoder and the cable
output are basically sound. Everything that turns those parts into an
unattended broadcast station is not. The schedule did not drive what
went to air even once in eight hours, the playout workers could not stay
alive for more than a few minutes at a stretch, and twenty times a
routine programme change silently killed the channel in a way the
product then interpreted as intentional and refused to recover from. The
one alert that exists cannot say which channel is dark, the health
screen reported all-clear while a channel was dead, and captions --- the
legally load-bearing feature --- failed their own verification on all
three channels while the interface described the failure as \"not yet
confirmed\". A city that installed this build and went home would come
back to a dark channel and a station that believed everything was fine.
