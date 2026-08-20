# BYO-SDI Relay + OBS Bridge Doc (issue #117, Scott's option c) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Stacked on work/filler-gap-length (rebase onto main once the CA-8 fixes merge).

**Scott's decision (option c):** full SDI wiring in the product, with the station supplying the SDI side — a DeckLink-capable FFmpeg build (Blackmagic's SDK license is theirs to accept; mainline builds don't ship `--enable-decklink`) and the physical card. Identical BYO posture and architecture to the NDI relay (#116/#149): supervised side-relay consuming the channel's TS output, honest blocked states, never a faked readiness. Physical proof happens at the test station (LPM has the DeckLink); CAPABILITIES claims `real component (config-gated, BYO ffmpeg, card proof pending)` until then.

**Why a side-relay again:** same three reasons as NDI — the BYO binary isn't the bundled encoder's; SDI output needs a raw video re-encode leg (decklink takes uncompressed frames); a dying SDI feed must never take the cable channel off air. Everything the channel plays flows through for free.

## Pieces
1. **`civiccast/egress/sdi_relay.py`** (new, TDD; mirror `ndi_relay.py`):
   - `SdiRelaySettings.from_env()`: `CIVICCAST_SDI_FFMPEG` (DeckLink-capable build; may be the same binary as the NDI one), `CIVICCAST_SDI_RELAY=inline|off`.
   - `check_sdi_runtime(ffmpeg_path)`: `ffmpeg -muxers` contains `decklink` → ok; plus `-sinks decklink` device listing helper for the operator (list available cards).
   - `build_sdi_relay_args(source_uri, device, *, video_size, framerate)`: `-i <udp ts> -vf scale=...,fps=... -pix_fmt uyvy422 -f decklink "<device>"` (audio: decklink takes pcm_s16le -ar 48000; include `-c:a pcm_s16le -ar 48000 -ac 2` — unlike NDI we keep audio, SDI embeds it).
   - `SdiRelaySupervisor`: same poll-driven lifecycle as NdiRelaySupervisor (blocked w/o binary/muxer/device, 5/15/60s backoff, stop), status registry (`sdi_relay` statuses module-level like NDI's).
   - Refactor note: extract the shared supervisor bones ONLY if it stays readable — duplication of ~100 lines between ndi_relay/sdi_relay is acceptable for clarity; decide at implementation.
2. **Durable config**: `egress_configs.sdi_relay_device TEXT NULL` — **migration 0036** (parent 0035; advance the head pin).
3. **Automation wiring**: `_sync_sdi_relay(config)` alongside `_sync_ndi_relay` in run_once (factory seam for tests).
4. **Staff API**: `GET /api/staff/egress/sdi-readiness` (BYO posture + device list when available + relay statuses).
5. **Console**: "SDI output device" field next to the NDI name on the channel automation panel (blank = off) + readiness copy; e2e asserts the config PUT body.
6. **Docs**:
   - Runbook "SDI output (bring your own DeckLink-capable FFmpeg)" — what the station brings (card, Desktop Video driver, ffmpeg w/ decklink), device naming (`ffmpeg -sinks decklink`), the receiver-proof boundary (a real monitor showing the feed at the test station).
   - **OBS bridge section** (the no-custom-ffmpeg path): channel TS/SRT into OBS (Media Source udp:// or SRT) → OBS DeckLink output — for stations that already run OBS + DeckLink; step-by-step.
   - CAPABILITIES SDI row: from `deferred`/stub language to `real component (config-gated, BYO ffmpeg, card proof pending at the test station)`.
7. **Existing `sdi` sink stub** (sinks.py SdiSink raising NotImplementedError): leave as-is (encoder-output-leg SDI stays out of scope); its message should now point to the SDI relay ("configure the channel's SDI output device") — small copy update + test pin if one exists.

## Steps
plan commit → sdi_relay module TDD (RED first) → migration 0036 + model/store round-trip + head pin → automation wiring TDD → API TDD → console + e2e → docs (runbook incl. OBS bridge; CAPABILITIES) → OpenAPI regen → full gate (after rebase onto main post-CA-8-merge) → PR `Closes #117` → merge.
