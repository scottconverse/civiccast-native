# Stage 3 Control Room Device Adapters

Audience: station admins, meeting operators, and technical operators validating
control-room device control before live use.

## Device Inventory

Register each controllable device with a plain operator label, device kind,
transport, host policy, and channel scope. Stage 3 covers the first complete
adapter family:

- vMix HTTP/API for the streaming PC or laptop.
- OBS obs-websocket 5.x for local studio and digitization workflows.
- ATEM simulator for the portable field-kit switcher contract.

Credentials must be stored through a keyring reference. Do not place OBS
passwords, vMix credentials, or device secrets in device notes, cue payloads,
support bundles, logs, screenshots, or exported JSON.

## Cue Builder

Use cue builder to create small, explicit actions such as vMix input select,
vMix transition, OBS scene select, OBS overlay clear, ATEM input select, and
ATEM transition. CivicCast intentionally does not expose destructive setup
mutations such as vMix input rename, input delete, recording destination change,
or global application configuration changes as live cues.

Every cue belongs to one channel or control surface. Per-channel cue scoping
keeps a public-channel action from accidentally firing on the government or
education workflow.

## Dry Run

Dry run resolves the device, action, payload, profile timing, and material-state
fingerprint without opening a device socket. If the device state changes after a
dry run, the operator must dry-run again before live fire.

Treat these dry-run failures as blocking:

- unsupported action for the device kind,
- public host without a setup-admin override reason,
- missing OBS source,
- vMix input identity drift,
- ATEM busy transition,
- stale material-state fingerprint.

## Live Fire

Live fire sends the already-reviewed action through the local TSR sidecar and
writes an audit record. The operator should only live-fire after the dry-run
preview matches the intended show state.

Test Mode records planned cue events and blocks device commands. On-Air Mode
requires an explicit confirmation and a confirm-required safe-state panic cue.
If On-Air Mode expires, open a new on-air session before firing additional cues.

## Safe-State Panic And Rollback

Each on-air surface must have a safe-state panic cue that can return the channel
to known-good filler or other station-approved material. Rollback should use the
last known-good cue version, not a newly edited untested cue.

Cue versioning and cue history are part of the audit trail. Do not overwrite a
working emergency cue without retaining the previous safe version.

## Adapter Notes

vMix HTTP/API uses status XML and function calls. Stage 3 proofs parse the vMix
status XML and model active/preview inputs, recording state, stream state, and
input identity drift.

OBS obs-websocket 5.x uses the versioned websocket protocol. Stage 3 proofs
model Hello, request/response correlation, event subscription, recording state,
disabled websocket setup guidance, wrong-password failure without logging the
secret, and protocol mismatch.

The ATEM simulator models program input, preview input, transition state,
SDK/protocol drift, switcher absence, and a duplicate transition fired while
one is already in progress. Physical ATEM switcher proof is separate station
evidence.

### Item 11: PTZ / VISCA / AIDA

PTZ support is represented in Stage 3 by the VISCA UDP command model. The
proof checks command encoding, command acknowledgment shape, response parseability,
and completion semantics for safe-home, stop, and lock states without touching a
physical PTZ camera. This proof remains software-envelope only and is explicit
about hardware execution deferment.

Stage 3 proof documents include PTZ and router-aware control semantics as part of the
NDI/adapter envelope.

### Item 12: NDI Integration

NDI coverage validates discovery topology, studio-monitor presence, and stable
source manifests. Stage 3 checks include discovery server identifiers, source
identity, and monitor dependency state so teams can confirm interoperability
contracts before cable deployment. Live on-air NDI ingest quality is not implied by
the software contract alone.

This includes an NDI discovery clause (`ndi discovery`) for deterministic proof and
source-identity replay checks.

### Item 13: DeckLink and Capture-Card Profile

DeckLink proof exercises capture identity fixtures: channel enumeration, capture
profile binding, and driver family detection shape. This is a deterministic local
fixture proving identity/profile handling for USB and PCI capture paths. Physical
device and SDK integration is treated as separate lab scope.

The stage also includes explicit USB capture path coverage and capture-card profile
validation.

### Item 14: Audio Mixer and Audio Device Layer

The audio layer proof covers Allen & Heath SQ, Yamaha TF, Behringer U-Phoria, USB
audio, and system-audio bindings. Stage 3 validates topology visibility, mixer
family metadata, and fail-safe pathing when an audio route is unavailable. Allen
& Heath SQ additionally gets real SQ MIDI Protocol message-format validation
(mute, NRPN fader/parameter writes, scene recall); Yamaha TF has no MIDI
implementation at all per Yamaha's own manual, so it stays at topology-only
proof rather than a faked control surface. See
[stage3-audio-mixer-device-layer.md](stage3-audio-mixer-device-layer.md) for
the full device inventory, protocol citations, and the documented Yamaha gap.

### Item 15: Routers, Videohub, Encoders, and Destination Profiles

Router and videohub egress proofs cover routing maps, route health, destination protocol
profiles, stream-key masking, retry policy metadata, and route/retry drift
classification. This stage proves destination and headend profile handoff
semantics; it does not claim cable-level headend transport success.

The router contract text includes explicit `router` and destination profile checks to
keep deterministic proof bounded.

## Locks, Reconnect, And Concurrency

Only one operator should hold a live-fire lock for the same control surface.
When a device disconnects or restarts, keep existing audit history, mark the
current dry-run preview stale, wait for reconnect grace, and dry-run again.

## Audit And Support Bundle

The audit record should show who planned or fired the cue, the cue id, device
id, action, mode, result, timestamp, material-state fingerprint, and redacted
device-state detail.

Create a support bundle when a control-room action is blocked or degraded. The
bundle should include device inventory, cue plans, cue audit, adapter contracts,
failure matrix, and operator action list. It must redact secrets and must not
include provider credentials, passwords, private keys, stream keys, subscriber
data, or private meeting content.

## Proof Boundaries

The Stage 3 local proof is deterministic software evidence. It is not physical
station-device proof, cable-headend proof, or live local OBS/vMix process proof
unless a separate software-lab run records that evidence.
