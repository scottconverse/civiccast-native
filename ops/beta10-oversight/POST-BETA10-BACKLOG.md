# CivicCast - improvements queued for after beta.10 (Scott, 2026-09-24)

All licence-compatible (Apache-2.0 product; LGPL/MPL runtime deps OK; no GPL/AGPL/non-commercial).
Source: research\RESEARCH-PRIOR-ART-2026-09-24.md. Scott said: "Don't forget these."

1. **fallbackswitch (MPL, gst-plugins-rs)** in place of input-selector: drops data from inactive inputs instead
   of blocking on them. Already in the official Windows GStreamer build. Targets the switch wedges/desyncs
   (U13, U15, U16 class).
2. **hlssink3 (MPL)**: write HLS straight from GStreamer; removes the separate ffmpeg relay, which is where the
   audio-only / video-only lock-ups come from (U12 class).
3. **NVIDIA hardware H.264 encode (nvh264enc, LGPL; NVIDIA headers MIT)**: frees the CPU that live captions keep
   losing (caption-tap pauses, U10/U11 class). Owner question still open: H.264 patent posture for hardware
   encoders (default: keep openh264 unless Scott says otherwise).
4. **Skip the double encode at preparation**: program video is encoded twice before air; the first (conform)
   pass can stream-copy video when it already fits.
5. **Two-pass loudnorm at preparation**: fixes content-dependent loudness (education measured -18.1 LUFS in a
   dry run vs -16+/-1 target). NOTE: this one may be pulled INTO beta.10 if the final acceptance loudness check
   fails again - coordinator decides from the rung evidence.

**Blocker found 2026-09-24 (U16 part 2):** the shipped `gsthlssink3.dll` aborts at plugin registration (Rust panic, "Failed to find element factory giostreamsink") because the GStreamer GIO plugin (`gstgio`, LGPL) is not in the runtime closure. Item 2 needs the closure to add gstgio first.

- (2026-09-26, U50 sec.4) live-hls fossil segments: relay never clears its HLS dir on start; 35-43 stale seg*.ts per channel from every restart since 09-19. Clean the dir (seg*.ts + playlist) at relay start. Writer: civiccast/egress/sinks.py:260.

## Pipe-accept leak parks teardown in CloseHandle (filed 2026-09-26 by U53 round 4)
A channel whose worker never connects (crash during worker startup, station stop in that window) leaves a
`civiccast-pipe-accept-<channel>` thread in ConnectNamedPipe; `WindowsWorkerPipeServer.close` (`gst/strategy.py:407/412`,
via `_WindowsPipeChannel.close` `:589-590`) then blocks forever. Fix: bounded ConnectNamedPipe/CancelIoEx, or close
only after joining the accept thread. Details: reports\U53.md Part IV §IV.5. Test harness has a workaround only.

## Outgoing programme's last ~0.57 s of VIDEO never reaches the selector (found U56 round 4, 2026-09-27)
Prepared plan files have video and audio ending together (deltas <= 31 ms), but the live outgoing leg's video pad
delivers ~0.57 s less than the file (education fae37c5d416a seg-0001: file ends 1801.4 s both streams; pads read
video=10798.900 audio=10799.467). U56c (switch at the shorter leg) removes the resulting picture hole by trimming the
matching audio tail, so each programme loses its last ~0.5-0.8 s of picture AND sound. Root cause (decoder/queue
behaviour at leg EOS dropping trailing frames) is not diagnosed. Evidence: staging\U56c\evidence\item1-prepared-asset-asymmetry.json.

## Published HLS playlist can reference an already-deleted segment (seen once, 2026-09-27 05:32:57)
Rung 8h-post-c5 loudness #4: education's first playlist poll referenced seg000003065.ts which was already gone
(capture_emitted_hls_audio_proof INSTRUMENT_ERROR). ffmpeg hls muxer uses delete_segments with the default
hls_delete_threshold=1 (sinks.py:370-380), so ffmpeg itself should not delete a listed segment; the relay publishes
the manifest from a staging copy (hls_relay.py connect_target -> manifest_target), so a manifest lagging >1 segment
behind ffmpeg's pruning would reference deleted files -> viewer 404s. One occurrence in ~21 channel captures.
Candidate fix: -hls_delete_threshold >= 3, or publish the manifest atomically with ffmpeg's own write.

## Caption tap falls behind under conform load (C11 8h rung, 2026-09-28)
control_plane-app.log "Caption tap is behind for channel X: N settled segments is over the maximum 2" logged 191x
22:30-04:25 (education 65, government 51, public 75); N mostly 3-4, max 6 (~12 s of lag), clustered during heavy
cold/repeat preparations (50-55/h). Self-recovers and every caption verify passed, but live captions can run up to
~12 s late while a conform runs. Expect fewer after U61 (C12) removes repeat conforms; re-measure on C12. Candidate
fixes: lower conform priority / cap conform threads, or reserve cores for the caption tap.

## Caption decode-back check cannot tell room tone from speech (C11 verify #19, 2026-09-28)
Pre-meeting room noise at -18 LUFS is "not silent", so a no-speech minute FAILs caption_decode_back instead of being
excused. Evidence: evidence\rung-8h-post-c11b-20260927-223728\VERIFY-19-NOTE.md. Fix: VAD or cross-check against the
source VTT / ASR receipt before failing.

## Operator status hides the in-worker slate; single warm FIFO; warm state lost on restart; 6 h failure backoff;
## three 4 h conforms exceed the 20 GB cache budget; misleading "270 s" parenthetical in the lead log line
(From U60/U61 reports, 2026-09-27; see reports\U60.md, reports\U61.md.)

- (2026-09-28, C14) Sub-second tail piece in a first-attempt plan: government 12:58 built a 3-segment plan whose first piece was a 0.2 s tail of the closing item; the worker's decodebin errored on it ('general stream error'), the reload aborted, and the daemon's retry path dropped the tail ('resolved to a 0.2s tail ... using the plan due where that tail ends instead') and succeeded. Self-healed with no on-air effect, but the first-attempt planner should apply the same sub-second-tail rule the retry path already has, so a reload never depends on the retry budget (2).
  - Second occurrence (soak, public 23:44): first piece a ~1 s tail of "Longmont Weather Report: July 16-21, 2026"; worker
    aborted:timeout (not decodebin error) 12 s after accept; retry re-resolved as a 0.7 s tail and dropped it, re-prepped
    16.7 s, accepted 23:45:16. So the threshold is not just sub-second at plan time: a ~1 s tail can shrink below 1 s by
    the time the worker reaches it. The first-attempt rule should use a margin (e.g. drop tails < 2 s).
  - Third occurrence (8h2, public 00:17:23): 0.2 s lead tail -> worker aborted:error 2 s after accept; retry dropped the tail,
    re-prepped 1 segment in 2.3 s, accepted 00:17:26 (~6 min before the ~00:23 boundary). Also logged: the discarded attempt's
    settlement "arrived after that attempt was already discarded ... ignoring" at 00:17:26 - harmless here, but confirms the
    worker keeps running the discarded plan briefly. Three occurrences in ~12 h of C14 air: fix is worth pulling forward.
  - Correction/nuance (8h2, public 00:30:41): the FIRST-attempt planner already drops a sub-second tail when it is sub-second
    at plan time ("resolved to a 0.4s tail ... using the plan due where that tail ends", no abort). So the failing cases are
    tails that are >= ~1 s at first plan and shrink below 1 s by the time the worker reaches them. Fix stands: widen the
    first-attempt threshold to ~2 s (or re-check at worker hand-off).
  - Fourth occurrence, on C15 (U63 installed), education 04:22:19: the AUTOMATION dropped the 0.7 s tail at 04:19:42 (U63 fix A
    line), but the DAEMON's own first-attempt prepare still built a 3-segment plan starting with that tail (142.5 s prep),
    worker aborted:timeout 12 s after accept, retry dropped the tail, 1 segment in 2.4 s, accepted 04:22:22 (~9 min before
    the ~04:31 boundary). So U63 fixed the automation's decision but not the daemon's first-attempt plan build: the daemon's
    first attempt must apply its own _resolve_schedule_tail rule (or honour the automation's resolved boundary). Still
    self-heals; no on-air effect so far in 4 occurrences.

## Full-asset conform rebuild churn (C15 rung 2026-09-29) - HIGH, load behind caption-tap discards
- August 11 (4.4 h, ~11 GB) re-conformed 00:55, 07:53, 10:12. Two producers:
  1. probe-only sidecar write clobbers a promoted conform's markers under concurrent prepares - FIXED in U65
     (staged, audited ACCEPT 2026-09-29, not installed).
  2. conform-cache budget 20 GB default vs ~11 GB per long-asset conform -> eviction thrash (U65 measured). Needs a
     sizing decision (budget vs free disk on the appliance) - not yet made.
  3. 07:53:54 rebuild cause unresolved (U65 §2(b)); next instance to probe named in reports/U65.md.
- Related: caption-tap discards under prep/conform load (5 s / 20 s / 50 s on C15) - give the caption tap priority.
- Related: rung loudness adjudicator position fix (briefs/U66-draft.md) - oversight tooling, before the next rung.
- U64 station candidate (quiet-source exclusion in the ride gate, log-only) and its re-ride recommendation - parked.

## Caption-tap discards persist on C16 (2026-10-01, from the final 8 h run)
Measured on C16 (U65 + U67 + 60 GB cache): the caption tap still discards audio when it falls 9+ segments behind for a whole
15-scan window: education 30 s (16:54), a cluster of 7 on all three channels 18:40-18:43 (confounded by coordinator disk scans), and
education 35 s at 19:34 with CPU ~50% and no preparation running. C15 had 5 s / 20 s / 50 s in 8 h. No verify has failed because of a
discard. Likely cause: ASR throughput shared by three channels against CPU contention; the tap catches up by dropping the oldest
audio. Fix direction: raise the tap's priority over prep/conform and/or increase its catch-up capacity; verify no caption regression.
Decision recorded as D5 in OVERSIGHT-LOG.md (option A: ship, fix after release).
Update 21:31: another discard (public 25 s) landed as government's cold 2-segment preparation (344 s) finished. Pattern: discards cluster
around long cold preparations, confirming prep/conform CPU load as the cause. The 21:31 speech-leveling warning (worst 4-minute stretch
1.94 LU on "Serving Locally ... Wildlands Restoration Volunteers") is the ride's own gate miss on a 33 min asset; whole-program level -0.02 LU.
Update 22:55 (C16 final run): the daemon first-attempt abort happened twice on government, both on 3-segment programs with a sub-second boundary tail
(22:23 aborted:timeout, tail 0.7 s; 22:55 aborted:error, tail 0.2 s). Both recovered by "retry 1 of 2" within ~5 s and ~25 s to on-air, outgoing leg
kept airing, no viewer-visible effect. Pattern for the fix unit: multi-segment prep + tail < 1 s at the boundary makes the first reload abort.
