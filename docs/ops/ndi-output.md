# CivicCast NDI Output Ops

CivicCast v1.2 adds an NDI output planning and readiness surface for cable
integrators who want to route a local recording into an NDI receiver or monitor.
This is not SDI, DeckLink, live cable headend delivery, or real station proof.

## What This Proves

Implemented in this slice:

- `civiccast cable ndi-plan` builds the exact FFmpeg arguments for sending a
  local media file to a named NDI channel.
- `civiccast cable ndi-check` checks whether the host has FFmpeg and whether
  that FFmpeg build exposes an NDI output muxer or whether the local internal
  FFmpeg-to-NDI sender is available.
- `tools/ndi-ffmpeg-sender` launches FFmpeg, reads rawvideo from FFmpeg stdout,
  and publishes the frames through the local NDI runtime for internal station
  testing.
- blocked states tell the operator what to install or verify next.

Not claimed in this slice:

- receiver-side NDI proof;
- public redistributable FFmpeg+NDI binaries;
- live cable headend delivery;
- SDI or DeckLink output;
- FCC Part 79 field certification;
- real station cable proof.

## Readiness Check

```bash
civiccast cable ndi-check
```

Use `--json` for automation. The command returns:

- `ok` when FFmpeg is present and lists an NDI output muxer;
- `ndi_sender_ready` when FFmpeg lacks an NDI muxer but the local internal
  FFmpeg-to-NDI sender tool is built;
- `runtime_unavailable` when FFmpeg is missing or cannot list muxers;
- `ndi_muxer_missing` when FFmpeg is present but does not include NDI output
  support.

## Internal Lab Sender

Build the internal sender:

```powershell
cd tools\ndi-ffmpeg-sender
cargo build --release
```

If Windows cannot find `Processing.NDI.Lib.x64.dll`, copy the installed NDI
Runtime DLL next to the built executable:

```powershell
Copy-Item "C:\Program Files\NDI\NDI 6 Tools\Runtime\Processing.NDI.Lib.x64.dll" `
  "tools\ndi-ffmpeg-sender\target\release\Processing.NDI.Lib.x64.dll"
```

Send a test source:

```powershell
tools\ndi-ffmpeg-sender\target\release\civiccast-ndi-ffmpeg-sender.exe `
  --name "CivicCast Lab Proof" `
  --duration-seconds 30
```

Open NDI Studio Monitor and select the named source. This is an internal lab
proof path, not a public redistributable FFmpeg+NDI binary.

## Output Plan

```bash
civiccast cable ndi-plan \
  --media /recordings/council-2026-05-08.mp4 \
  --ndi-name "CivicCast Council Room"
```

The generated arguments use realtime file playback, scale to `1920x1080`, set
`30000/1001` fps, use `uyvy422`, and target the `libndi_newtek` FFmpeg muxer
by default. Operators should run the generated command only on a host with an
NDI-capable FFmpeg build and an NDI receiver or monitor available.

## Proof Boundary

The NDI output surface is ready for a future proof lane, but a release may not
claim live NDI delivery until a receiver-side proof artifact exists. The proof
artifact should name the host, FFmpeg build, NDI muxer, receiver or monitor,
source media hash, channel name, and observed receiver result.
