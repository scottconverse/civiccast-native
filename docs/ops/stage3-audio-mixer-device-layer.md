# Stage 3 Audio Mixer and Audio Device Layer

Audience: station admins and technical operators setting up or troubleshooting
the audio path before live use.

This page covers audit item 14: the software layer for mixer/device profiles
named in the 3.3-to-4.0 sprint plan (Allen & Heath SQ, Yamaha TF, Behringer
U-Phoria, generic USB audio, and system audio). It follows the same pattern as
[stage3-control-room-device-adapters.md](stage3-control-room-device-adapters.md):
deterministic local fixture proof, not physical station-device proof.

## Device Inventory

| Device | Class | What CivicCast proves locally | Live console control |
| --- | --- | --- | --- |
| Allen & Heath SQ5 (SQ series) | `audio-mixer` | Topology declaration shape; SQ MIDI Protocol message format (mute, NRPN fader/parameter writes, scene recall) | Message-format only -- no live socket to a powered-on mixer |
| Yamaha TF (TF1/TF3/TF5/TF-Rack) | `audio-mixer` | Topology declaration shape only | None -- see "Yamaha TF: a documented gap" below |
| Behringer U-Phoria | `usb-audio` | USB audio device presence/absence, sample-rate match, A/V sync delay | None (USB audio class device, no remote control surface) |
| Generic USB audio | `usb-audio` | Same as Behringer U-Phoria -- the presence/sample-rate/sync checks are device-name-agnostic | None |
| System audio (OS default output/input) | `usb-audio`-shaped fixture | Same presence/sample-rate/sync checks apply to a system-audio device entry | None |

Register each mixer with a plain operator label, model, channel count, and its
documented output routes (program mix, stream mix, monitor mixes). CivicCast
records this as topology context for the support bundle and device inventory
-- it is not a live control connection.

## Allen & Heath SQ: the deep-support device

Allen & Heath publishes an official **"SQ MIDI Protocol" (Issue 5)** PDF,
covering SQ5/SQ6/SQ7 firmware V1.5.0+. It documents:

Byte formats below are quoted from the Issue 5 PDF (page/section noted), not
inferred. `BN`/`CN` = status byte with MIDI channel nibble `N`.

- **Transport** (page 6-7): MIDI-over-TCP on **port 51325** (also available
  over USB-B).
- **Fader / level writes** (page 12, §3.4 "Levels"): a 4-message **NRPN**
  sequence -- `BN 63 MB` (CC 99, NRPN MSB), `BN 62 LB` (CC 98, NRPN LSB),
  `BN 06 VC` (CC 6, Data Entry MSB / value coarse), `BN 26 VF` (CC 38, Data
  Entry LSB / value fine).
- **Mute** (page 11, §3.3 "Mutes"): the **same 4-frame NRPN shape**, with the
  data entry fixed -- `BN 63 MB` / `BN 62 LB` / `BN 06 00` / `BN 26 01` for
  mute **on**, and `... BN 26 00` for mute **off**. The doc's own example is
  `B0 63 00 B0 62 00 B0 06 00 B0 26 01` (Ip1 Mute On, Ch1). Mute is **not** a
  Note On message.
- **Scene recall** (page 9, §3.1 "Scene change"): a bank change followed by a
  Program Change -- exactly **two** messages, `BN 00 BK` (CC 0, bank) then
  `CN PG` (Program Change). There is **no CC 32** (Bank LSB). The doc's own
  example is `B0 00 00 C0 06` (Scene 7, Ch1).
- **Note On/Off** (pages 8, 10, §3.2 "Soft Keys"): used for Soft Keys and MIDI
  strip keys (`9N SK 7F` press / `8N SK 00` release) -- a **different**
  function from mute.

CivicCast validates these message shapes against fixtures built from the spec
(`validate_midi_nrpn_message`, `validate_sq_midi_mute_message`,
`validate_midi_scene_recall` in `lpm_lab_stage45.py`) and rejects a malformed
or out-of-order message --
including rejecting the two formats an earlier draft got wrong (a Note-On
"mute" and a scene recall carrying a spurious CC 32). This proves CivicCast's
parser is correct against the vendor's own published byte layout. It does
**not** prove CivicCast has opened a live socket to a powered-on SQ5 and moved
a real fader -- that requires a real console capture session and is separate,
hardware-gated proof.

The specific NRPN number assigned to a specific SQ5 fader/channel is a lab
fixture in CivicCast's tests, not independently confirmed against a live
console; do not treat the fixture's NRPN numbers as a working preset.

## Yamaha TF: a documented gap, not a fake pass

Yamaha's own TF series Reference Manual and product FAQ (checked directly)
confirm the TF series **has no MIDI implementation at all**:

- No MIDI DIN port and no MIDI-over-network port on any TF model.
- Zero mentions of "MIDI" anywhere in the official Reference Manual.
- Yamaha's own FAQ states TF "doesn't have any DAW control function."

The only network remote-control surface for TF is a separate, non-MIDI,
plain-text TCP protocol informally called "RCP." Yamaha has never published
this protocol for the TF line -- it is known only through unofficial
community reverse engineering (for example, `github.com/BrenekH/yamaha-rcp-docs`
and the `bitfocus/companion` project).

CivicCast does not build a control validator against RCP. Two reasons:

1. Yamaha's EULA prohibits reverse engineering, and CivicCast is an
   Apache-2.0 open-source project -- a shipped feature or claim must trace
   to a primary, vendor-published source, not a reverse-engineered one.
2. An unofficial spec is not independently verifiable, so a "validator"
   built on it would be exactly the kind of unearned pass this audit item
   exists to remove.

**Result: Yamaha TF gets topology/inventory-level proof only** (the same
`validate_audio_topology_fixture` / `validate_audio_control_not_claimed`
checks every mixer gets), and nothing deeper. This is an honest-red gap, not
a stub pretending to be a real check. It stays closed until Yamaha publishes
a public protocol document CivicCast can validate against, or a station
supplies its own confirmed protocol reference.

## USB Audio and System Audio

Behringer U-Phoria, generic USB audio interfaces, and the OS default system
audio device share one fixture shape (device `name`, `class`, `stable_id`,
plus `sample_rate_hz` and `delay_ms` for the sample-rate/sync checks). This
is deliberate: a USB Audio Class device or the OS's default output doesn't
need a brand-specific model, since the properties CivicCast checks (is it
present, does its sample rate match what the show expects, is its A/V delay
within tolerance) come from the OS audio-device enumeration layer, not from
a vendor-specific control protocol.

- **Presence / absence**: reuses the same capture-identity fixture format as
  USB video capture (`validate_capture_identity_fixture`), filtered to the
  `usb-audio` device class.
- **Sample-rate mismatch**: rejected against an expected rate (48 kHz in the
  reference fixture); a real mismatch must surface as an operator-visible
  warning, not be silently resampled or ignored.
- **Sync/delay warning**: rejected once A/V delay reaches or exceeds a
  40&nbsp;ms ceiling in the reference fixture; stations with a different
  tolerance can adjust the ceiling passed to `validate_usb_audio_sync_delay`.

None of these checks open an audio device or read a live sample stream; they
validate the shape and thresholds CivicCast's device-layer logic applies to
whatever the OS audio stack reports.

## Routing Assumptions

- CivicCast records an audio topology (mixer model, channel count, output
  routes) as **inventory**, not as a live routing engine. It does not claim
  to move audio between routes.
- A topology fixture that includes a control-capable field (a command
  endpoint, credential, API key, or MIDI port) is rejected outright by
  `validate_audio_control_not_claimed` -- the "no live control" boundary is
  an enforced contract, not a comment that can silently go stale as new
  fields get added.
- The fixed-studio profile's Allen & Heath SQ5 entry and the portable
  field-kit profile's Behringer U-Phoria entry are the two LPM-documented
  physical devices; generic USB audio and system audio are available as
  reusable device-layer capability for stations that aren't running exactly
  LPM's kit.

## Proof Boundaries

The Stage 3 audio-device local proof is deterministic software evidence over
published-spec fixtures. It is not physical station-device proof, and it is
not a claim that CivicCast has read levels, moved a fader, or toggled mute on
a powered-on Allen & Heath, Yamaha, Behringer, or system-audio device unless a
separate software-lab or station-device session records that evidence.
