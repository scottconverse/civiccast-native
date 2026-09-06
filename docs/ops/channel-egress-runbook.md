# Channel Egress Operator And Tester Runbook

This runbook explains how to operate and test CivicCast's local outgoing channel
feed. It is for meeting operators, station admins, integrators, and release
testers.

## What The Outgoing Feed Is

The outgoing feed is the local CivicCast worker that sends one channel to its
configured output, such as a cable handoff, SRT receiver, RTMP endpoint, or local
transport-stream file. It is separate from the resident portal player.

Use the outgoing feed when the station needs CivicCast to drive a linear channel
or a headend-style destination.

## What This Proves

The egress proof path can show:

- CivicCast queued a start, stop, reload, or drain command from a signed-in staff
  operator.
- The daemon started the configured source plan or fallback slate.
- The encoder reported health samples while running.
- The output file or receiver preserved the expected source duration and
  loudness boundary during local proof.
- Caption status changed to **On** only after decoded emitted-stream captions
  matched expected captions.
- CivicCast recorded emergency banner raise and clear events as CivicCast CG
  overlay intent, not as EAS proof.

The egress proof path does not by itself prove:

- a cable headend accepted the feed;
- a downstream station switcher rendered overlays correctly;
- legal caption compliance;
- ATSC A/85 or station-specific loudness compliance unless the configured
  target was agreed and measured for that handoff;
- app-store, CDN, external provider, or production operations readiness.

## Operator Checklist

1. Open the operator console.
2. Open **System Health** or **Channels**.
3. Find **Outgoing channel feed**.
4. Confirm you are signed in with the meeting operator role. If the buttons are
   disabled, ask an admin to assign the role or have a meeting operator run the
   command.
5. Check the channel state:
   - **Stopped:** no outgoing feed is running.
   - **On air:** the outgoing worker is sending the configured source.
   - **Showing slate:** CivicCast is sending fallback slate instead of blank
     output.
   - **Changing source:** CivicCast is switching from one source to another.
   - **Finishing current item:** CivicCast is draining before stopping.
   - **Needs attention:** read the error and ask a technical admin before
     retrying.
6. Use **Start** to begin the outgoing feed.
7. Use **Reload** after the schedule/source plan changes and the current worker
   should hand off to the new source.
8. Use **Drain** when the current item should finish before the worker stops.
9. Use **Stop** when the feed should stop now.
10. Watch encoder health, sink connection, loudness, dropped frames, and caption
    status.

Do not use outgoing feed controls during a live meeting unless station policy
allows the action you are taking.

## Tester Evidence Checklist

A tester should collect all of the following for a release or acceptance proof:

- CivicCast version, branch, commit, and artifact under test.
- Operating system and whether the test used a clean install, upgrade, or
  developer checkout.
- The configured channel id.
- The sink type under test: FileSink, SRT loopback, RTMP, local TS, SDI, or
  external headend.
- The configured loudness target and tolerance.
- The proof command used.
- The JSON proof output path.
- PASS, PARTIAL, or FAIL.
- Exact blocker code for any failure.
- A note that secrets, passphrases, tokens, recovery codes, subscriber data, and
  private URLs were not included in the report.

## FileSink Continuity Proof

Use FileSink when you need a local proof that does not depend on a receiver.

```powershell
uv run civiccast egress continuity-proof `
  --source-plan-json C:\path\to\source-plan.json `
  --config-json C:\path\to\egress-config.json `
  --output-path C:\path\to\evidence\egress-proof.ts `
  --work-dir C:\path\to\evidence\work `
  --json
```

Expected PASS evidence:

- `status` is `PASS`;
- `boundary_count` is greater than zero for a multi-source plan;
- measured duration is within tolerance;
- `loudness_status` is `ok`;
- `output_path` points to the emitted `.ts` file;
- `concat_plan_path` points to the generated FFmpeg concat plan.

If this fails, keep the JSON output and the generated work directory. Do not
delete evidence before a developer has read it.

## SRT Loopback Continuity Proof

Use SRT loopback when you need proof that CivicCast can send to a local SRT
receiver.

```powershell
uv run civiccast egress srt-continuity-proof `
  --source-plan-json C:\path\to\source-plan.json `
  --config-json C:\path\to\egress-config.json `
  --sender-url "srt://127.0.0.1:19001?mode=caller" `
  --receiver-url "srt://127.0.0.1:19001?mode=listener" `
  --receiver-output-path C:\path\to\evidence\receiver.ts `
  --work-dir C:\path\to\evidence\work `
  --json
```

Expected PASS evidence:

- `status` is `PASS`;
- `sink_kind` is `srt`;
- receiver return code is `0`;
- measured duration and loudness are within the configured target;
- receiver metrics and receiver output path are present.

This proves local SRT loopback. It does not prove a real cable headend accepted
the feed.

## Caption Decode-Back Proof

Caption status must stay **Not verified** until decoded emitted-stream captions
match the expected captions.

First, create or collect:

- the emitted stream file;
- the expected caption file as WebVTT or SRT;
- the decoded caption file from the emitted stream as WebVTT or SRT.

Then run:

```powershell
uv run civiccast egress caption-decode-proof `
  --channel-id public `
  --emitted-stream C:\path\to\evidence\egress-proof.ts `
  --expected-captions C:\path\to\expected.vtt `
  --decoded-captions C:\path\to\decoded-from-emitted-stream.vtt `
  --decoder-name ffmpeg-cc-decode `
  --output-path C:\path\to\evidence\caption-decode-proof.json `
  --json
```

Expected PASS evidence:

- `status` is `PASS`;
- `caption_status` is `on`;
- expected and decoded cue counts are present;
- matched cue count equals the expected cue count;
- max timing delta is within the configured tolerance;
- the emitted stream path points to a real file.

Expected FAIL evidence:

- `EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES` means the expected caption file
  did not contain timed cues.
- `EGRESS_CAPTION_DECODE_BACK_MISMATCH` means decoded captions did not match the
  expected text and timing.

Do not describe a PASS as legal caption compliance. It proves this emitted
stream's decoded captions matched the expected file under the configured
tolerance.

## Emergency Banner Proof

CivicCast can record emergency banner raise and clear events in the egress proof
log when the CG overlay path supplies a valid overlay proof.

Operators should understand this wording:

- **Emergency banner:** CivicCast visual banner intent.
- **Not EAS:** CivicCast is not claiming EAS origination, EAS certification,
  CAP relay, or alert authority.
- **Cleared:** CivicCast recorded that the banner was removed from the egress
  proof path.

If a report includes emergency banner evidence, it must say whether it is raise
or clear evidence and must not call it EAS proof.

## Running Three Channels On One Box

The cable-automation lane (CA-1..CA-4) runs multiple channels from the app
itself — no CLI worker needed. Posture for a three-channel station:

- Configure each channel's egress config (sinks, slate message, canonical
  profile), set `auto_start` for every channel that should run 24/7, and pick
  each channel's `fill_policy` (`slate` or `bulletins`).
- Each running channel is one ffmpeg encoder process. Three concurrent 720p
  H.264 encodes are the realistic load shape. The CA-8 4-hour development
  acceptance window measured flat combined encoder RSS of 49–89 MB across
  three channels on one machine (see
  `tester-handoff/v2.1.0/test-results/windows/20260612-0824-local-ca8-4h-acceptance.md`);
  full-day CPU/memory figures come from the pending 24-hour unattended
  soak — this runbook does not claim load figures that have not been
  measured.
- Work files live under `CIVICCAST_EGRESS_WORK_DIR/<channel_id>/` (prepared
  segments, slates, bulletin slides) — one subtree per channel.
- **Program-start speed and the conform cache (issue #156, fixed):** an asset
  that has aired before starts within seconds — its canonical conform is kept
  in a persistent cache (`CIVICCAST_EGRESS_WORK_DIR/conform-cache/`, bounded by
  `CIVICCAST_CONFORM_CACHE_GB`, default 20; set `0` to disable). The **first-ever
  airing of a long asset still conforms at airtime** (same duration as before —
  schedule long premieres with that in mind, or air a short lead-in first); a
  join-in-progress first airing conforms only the remaining portion, exactly as
  before, and the full asset is cached in the background for the next airing.
  Join-in-progress starts from the cache land on the nearest keyframe (at most
  one GOP — about 2 seconds — early); on the GStreamer engine the cached copy is
  re-cut by stream copy rather than re-encoded, which costs seconds, not
  minutes.
- **Cache HIT accuracy vs MISS accuracy (item 66):** a cache HIT's window is a
  `-c copy` cut out of the shared conform (fast, but floors to the previous
  keyframe — up to ~2 seconds early, per the keyframe note above); a cache
  MISS's bounded conform re-encodes the exact wanted window sample-accurately.
  On the GStreamer engine this means the FIRST airing of an asset (a MISS,
  re-encoded) can start slightly more precisely than a LATER airing of the
  same asset served from the cache (a HIT, keyframe-floored) — the opposite of
  what "cache = faster and better" intuition suggests. Neither is a defect;
  don't read a later airing's ~2s-early start as a regression from the first.

- Never run the inline automation driver AND a `civiccast egress run` CLI
  worker for the same channels: two daemons would race the same durable
  command queue.
- **Restarting the server process while channels are on air (issue #161,
  fixed):** before the startup reap shipped, the old server's encoder
  children survived the restart and kept streaming to the sink ports while
  the new server auto-started its own — two writers on one UDP port
  corrupts the headend feed (continuity errors) until the orphan's plan
  ends. The daemon now terminates any still-running encoder pid recorded in
  durable channel state before starting fresh and logs the reap as a
  channel event, so routine deploy restarts no longer need a manual stop
  sequence. If you are running a build older than the reap, stop the
  channels (or kill the ffmpeg encoder processes) BEFORE replacing the
  server process, then let `auto_start` bring them back. Found and
  root-caused by the CA-8 acceptance run's TSDuck monitoring; the
  post-fix server-restart case re-runs as part of the 24-hour soak.
- **Seamless mux across encoder relaunches (issue #151, fixed for udp-ts):**
  plan boundaries, reloads, and crash restarts relaunch the encoder, which
  used to reset the TS session at the headend (new continuity counters and a
  new source port at every splice — logged as CC errors by TR 101 290
  monitoring). With TSDuck available (`tsp` on PATH, `CIVICCAST_TSDUCK_PATH`,
  or the managed pull), a channel-lifetime relay now sits between the encoder
  and every `udp-ts` destination (`tsp -P continuity --fix -P pcradjust`,
  pinned source port), so the headend sees one continuous session no matter
  how often the encoder relaunches. `CIVICCAST_TS_RELAY=auto` (default:
  on when tsp exists) | `on` | `off`. Without TSDuck the behavior is the
  historical direct output, with a startup log telling you what you're
  giving up.
- System Health shows the "24/7 channel automation" rollup: green when every
  auto-start channel is on air (or honestly on schedule-gap filler), red with
  the channel ids when any automated channel is dark. A dark cable channel
  never blocks meeting-broadcast readiness — it is an optional check by
  design.

## Sending A Channel To A Cable Headend

The cable-automation lane (CA-6) ships a `udp-ts` sink — constant-mux-rate
SPTS MPEG-TS over UDP unicast or multicast — plus named presets built from
published vendor documentation. Apply one from **Channels → Cable headend
delivery** (or `POST /api/staff/egress/channels/{id}/config/headend-profile`).

| Preset | Encode | Mux rate | Transport | Built from |
| --- | --- | --- | --- | --- |
| `generic-udp-spts` | H.264 720p30 5 Mbps, AC-3 192k | 8 Mbps default | UDP unicast | TelVue feed-setup KB; CableLabs encoding tech notes |
| `comcast-mtd-sd` | MPEG-2 720×480, GOP 15, AC-3 192k/48k | 3.75 Mbps (CableLabs SD aggregate) | UDP multicast | Comcast MTD page; CableLabs VOD encoding profile |
| `comcast-mtd-hd` | H.264 1080p30 10 Mbps, AC-3 384k | 12 Mbps placeholder — your carriage agreement sets the real rate | UDP multicast | Comcast MTD page |
| `telvue-hypercaster-ip` | H.264 720p30 5 Mbps, AC-3 192k | 8 Mbps; match the feed's Max Bit Rate | UDP unicast or multicast, port 1024–65535 | TelVue KB (feed setup, content prep, ports) |
| `harmonic-spectrum-ts` | H.264 1080p30 8 Mbps, AC-3 192k | 10 Mbps | UDP unicast | Harmonic Spectrum X/XE datasheets |
| `leightronix-file-drop` | H.264 720p file handoff | n/a | Watched folder | Leightronix UltraNEXUS-HD docs |

Mechanics worth knowing:

- The **mux** is what must be constant (TelVue documents this explicitly):
  the `-muxrate` flag makes the mpegts muxer null-pad to the constant rate,
  so the requirement holds even though the encoder stream-copies prepared
  segments. The encode numbers land on the channel's canonical profile, so
  every prepared segment conforms before air.
- Datagrams carry seven 188-byte TS packets (`pkt_size=1316`) unless you pin
  a different `pkt_size` on the destination URI yourself.
- Multicast presets refuse a unicast destination; unicast presets accept
  either (a multicast group is still valid). The TelVue preset enforces the
  KB's 1024–65535 port floor.
- The operator supplies ONLY the destination address/port and, where the
  carriage agreement sets one, the mux rate. Everything else is baked from
  the published docs.
- **Honesty boundary:** these presets are built from published vendor
  documentation and verified machine-locally. None of them is field-proven
  against a real cable headend until the first-station beta.

## Verifying The Headend Stream

CA-7 ships a bring-your-own-TSDuck verification lane. TSDuck is the free,
BSD-licensed MPEG-TS toolkit from <https://tsduck.io>; install it (or set
`CIVICCAST_TSDUCK_PATH` to its `bin` directory) and CivicCast can capture
and judge the live udp-ts output.

Three ways to run the same probe:

- Console: **Channels → Cable headend delivery → Verify stream (TSDuck)**.
- API: `POST /api/staff/egress/channels/{id}/compliance-probe`.
- CLI: `civiccast egress verify --channel-id <id> --seconds 10` (exits 1 on
  fail — loopable for soak monitoring).

What the probe judges (a bounded `tsp ... -P analyze --json` capture):

| Check | Pass means |
| --- | --- |
| `cbr-mux-rate` | measured PCR bitrate within 5% of the sink's `-muxrate` |
| `ts-sync` | zero invalid sync bytes, zero transport-error indicators |
| `continuity` | zero continuity-counter discontinuities on every PID |
| `pat-pmt` | PAT and PMT both present |
| `pcr-present` | at least one PID carries PCR |
| `single-program` | exactly one service (a true SPTS) |

Mechanics and honesty:

- Multicast destinations are probed **alongside** the live headend (one more
  group member). Unicast destinations are probed **in place of** the
  receiver during commissioning — UDP unicast has one listener per port.
- Without TSDuck the verdict is an honest `not-run` with the install
  pointer; CivicCast never fakes a pass.
- These checks are an analyze-plugin subset aligned with TR 101 290
  priority-1 concerns — not the full TR 101 290 monitoring suite, and not
  headend field proof. System Health carries a "Cable headend verification"
  rollup (yellow when TSDuck is missing or channels were never verified,
  red on a failing last probe).
- A reference run on this machine: a CA-6-shaped stream (`-muxrate 8000k`)
  measured **exactly 8,000,000 b/s (0.00% drift)** with zero errors on
  every check; a deliberately double-sourced stream failed `continuity`,
  which is the probe doing its job.
- `POST /api/staff/egress/headend-device-probe` ({host, ports}) checks TCP
  reachability of the headend appliance's management surface (TelVue and
  Leightronix boxes manage over their web UIs) — reachability of the web
  UI says nothing about the video path; use the stream probe for that.

## NDI Output (Bring Your Own NDI-Capable FFmpeg)

Issue #116: CivicCast can republish any channel as an NDI source for the
station's production network — with the NDI side supplied by the station,
because mainline FFmpeg removed the NDI muxer in 2019 over the NewTek
license and CivicCast's bundled ffmpeg cannot and does not include it.

What the station brings:

1. The NDI runtime / NDI Tools from <https://ndi.video> (their license to
   accept).
2. An FFmpeg build with the NDI muxer (`libndi_newtek`), self-built against
   the NDI SDK or obtained from an integrator. `civiccast cable ndi-check`
   reports exactly what is missing.
3. `CIVICCAST_NDI_FFMPEG` pointing at that build.

What CivicCast does once the wire exists:

- Set the channel's **NDI output name** on the Channels screen (blank = no
  NDI). The automation driver supervises a relay process that consumes the
  channel's UDP transport-stream output and publishes it as that NDI
  source — programs, slate, and bulletins all flow through automatically.
- The relay is crash-isolated from the on-air encoder and restarts with
  5/15/60-second backoff. `GET /api/staff/egress/ndi-readiness` shows the
  BYO posture and live relay states; a missing binary or failed readiness
  check is an honest `blocked` status with the next step, never a crash
  loop and never a faked "running".
- The relay needs the channel's UDP TS output to exist (apply a headend
  delivery preset, or any `udp://` local-ts/udp-ts sink).
- `CIVICCAST_NDI_RELAY=off` disables NDI relay supervision host-wide
  (default `inline`); blanking a channel's NDI name field disables it per
  channel.

**Honesty boundary:** receiver-side proof is the station's step — an NDI
receiver (e.g. Studio Monitor) showing the stream is what makes NDI
delivery *proven* on that network. Until a station records that, CivicCast
claims a supervised, config-gated component, not field-proven NDI delivery.

## SDI Output (Bring Your Own DeckLink-Capable FFmpeg)

Issue #117: CivicCast can put any channel on a physical SDI wire through a
Blackmagic DeckLink output card — with the SDI side supplied by the
station, because FFmpeg's `decklink` output requires building against the
Blackmagic SDK (their license to accept) and CivicCast's bundled ffmpeg
cannot and does not include it.

What the station brings:

1. A DeckLink output-capable card and Blackmagic's **Desktop Video**
   driver installed on the playout host.
2. An FFmpeg build with the `decklink` muxer, self-built against the
   Blackmagic SDK (`--enable-decklink`) or obtained from an integrator.
   It may be the same binary as the NDI one if it was built with both.
3. `CIVICCAST_SDI_FFMPEG` pointing at that build.

Finding the device name (this exact string goes in the channel config):

```powershell
& $env:CIVICCAST_SDI_FFMPEG -sinks decklink
```

What CivicCast does once the wire exists:

- Set the channel's **SDI output device** on the Channels screen (blank =
  no SDI). The automation driver supervises a relay process that consumes
  the channel's UDP transport-stream output, re-encodes to the raw frames
  the card needs (`uyvy422` video, 48 kHz stereo PCM embedded audio), and
  feeds the named DeckLink device — programs, slate, and bulletins all
  flow through automatically.
- The relay is crash-isolated from the on-air encoder and restarts with
  5/15/60-second backoff. `GET /api/staff/egress/sdi-readiness` shows the
  BYO posture and live relay states; a missing binary or a build without
  the decklink muxer is an honest `blocked` status with the next step,
  never a faked "running". A malformed device name (blank, control
  characters) is rejected at save time and blocks honestly if it reaches
  the relay anyway. A syntactically valid name that matches **no installed
  card** is different: the readiness check cannot see the card, so the
  relay process exits and the supervisor retries on the same
  5/15/60-second backoff, showing `restarting` with the ffmpeg exit error
  captured in `last_error`. If the relay never reaches `running`, check
  the device string against `& $env:CIVICCAST_SDI_FFMPEG -sinks decklink`
  first.
- `CIVICCAST_SDI_RELAY=off` disables SDI relay supervision host-wide
  (default `inline`); blanking a channel's device field disables it per
  channel.
- The relay needs the channel's UDP TS output to exist (apply a headend
  delivery preset, or any `udp://` local-ts/udp-ts sink).

**Honesty boundary:** SDI is *proven* when a downstream device (headend
encoder, broadcast monitor) shows the feed from the card's BNC output.
Until a station records that, CivicCast claims a supervised, config-gated
component, not field-proven SDI delivery.

### No custom FFmpeg? Use the OBS bridge

Stations that already run OBS Studio with a DeckLink card can skip the
custom FFmpeg build entirely — OBS ships DeckLink output support and
Blackmagic's licensing is handled inside OBS:

1. Install OBS Studio and Blackmagic Desktop Video on the playout host;
   confirm the card shows up in OBS under **Tools → Decklink Output**.
2. Give the channel a UDP TS output (apply a headend delivery preset, or
   add a `udp://239.x.x.x:port` / `udp://127.0.0.1:port` sink).
3. In OBS add a **Media Source** to an empty scene:
   - uncheck *Local File*; set *Input* to the channel's `udp://` URI
     (or an `srt://` URI if the channel publishes SRT);
   - set *Input Format* to `mpegts`; leave hardware decode on if offered.
4. **Tools → Decklink Output** → pick the DeckLink device and a mode that
   matches the channel's canonical profile → **Start**.
5. The card's SDI output now carries the channel. OBS's media source
   re-opens a network input when data resumes on current OBS versions —
   verify the reconnect behavior on your OBS version during commissioning
   by restarting the channel once and watching the output recover.

The OBS bridge is operationally outside CivicCast — its supervision is
OBS's job, and the SDI readiness endpoint will not report it. It is the
right answer when the station wants SDI today without building FFmpeg.

## What To Do With Failures

Use the exact blocker code in the report. Do not paraphrase it away.

- If continuity fails, keep the output `.ts`, concat plan, JSON proof, and
  stdout/stderr logs.
- If SRT fails, keep sender and receiver command output, receiver metrics, JSON
  proof, and the receiver output file if one exists.
- If caption decode-back fails, keep expected captions, decoded captions, and
  the emitted stream file.
- If the operator UI blocks controls, record the visible role message and the
  staff role used for the test.
- If Windows, installer, WSL, or reboot behavior is involved, record exactly
  whether the test installed, cleaned, rebooted, restarted, or reused app state.

## Reporting Rules

Every report should use the narrowest true claim:

- **PASS:** the specific proof command and environment met the stated exit
  criteria.
- **PARTIAL:** some evidence passed, but a named part was skipped, unavailable,
  or inconclusive.
- **FAIL:** a blocker prevented the proof from meeting exit criteria.

Never turn a local proof into a broader claim. For example, SRT loopback PASS is
not a headend PASS, and caption decode-back PASS is not legal compliance.
