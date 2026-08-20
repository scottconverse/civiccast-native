# CivicCast Control-Room TSR Sidecar (S16)

A small **localhost** HTTP service that embeds [TSR (timeline-state-resolver)](https://github.com/nrkno/sofie-timeline-state-resolver),
the MIT-licensed device-control library extracted from the Sofie project, and
exposes the CivicCast-owned contract that the Python control plane calls. TSR
drives the station's existing production switchers (OBS / vMix / ATEM /
HyperDeck / PTZ / OSC / CasparCG, plus GPI/serial via the generic adapters).

## Why a separate Node process

TSR is a Node library. Running it as a separate process behind a CivicCast-owned
REST/IPC contract keeps **zero GPL/AGPL device-control code linked into the
Apache-2.0 CivicCast core**: TSR itself is MIT (vendored here); OBS/obs-websocket
(GPLv2), CasparCG (GPLv3), and vMix (proprietary) are reached only over their own
socket protocols by TSR, as separate processes. The Python plane never speaks a
device protocol directly.

## Contract (JSON, bound to 127.0.0.1 only)

| Method · path | Body | Returns |
|---|---|---|
| `GET /healthz` | — | `{ok, tsr}` |
| `POST /probe-device` | `{device, profile}` | `{reachable, capability_map, detail}` |
| `POST /apply-cue` | `{device, profile, action, payload}` | `{ok, detail, device_state}` |

The Python `HttpTsrClient` (`civiccast/control_room/tsr_client.py`) is the only
caller. It resolves the device secret from the keyring and POSTs it over loopback
only; the secret never leaves the box and is never persisted in the request.

## Run / install

- Point CivicCast at the sidecar with `CIVICCAST_CONTROL_ROOM_TSR_URL`
  (e.g. `http://127.0.0.1:7717`). Unset → CivicCast uses the fail-closed
  `NullTsrClient` (the control-room console shows "production control
  unavailable"; cues cannot fire).
- Start: `CIVICCAST_TSR_PORT=7717 npm start` (after install). Bound to 127.0.0.1.
- Install: `npm install --ignore-scripts --omit=optional`. TSR 9.3.2 targets
  Node 14/16/18; the S3 commissioning installer provisions a compatible Node.
  `--ignore-scripts` skips the optional `ws` native addons (`utf-8-validate`/
  `bufferutil`) — `ws` falls back to pure JS, and `node-gyp-build` is not
  required.

## Verification boundary (honest)

- **Machine-verified here:** TSR imports; the device-kind → TSR `DeviceType`
  mapping and the cue → timeline/mappings translation (`buildCueState`) use
  TSR's real enums (`builder.test.mjs`); the HTTP server + `/healthz` respond.
- **Rung-1 lab proof (LPM):** driving a *real* OBS / ATEM / vMix — opening the
  TSR connection (`connectionManager.createConnection`) to a live device and
  observing the device change on a fired cue — requires the physical device and
  is proven at the LPM lab, not in CI.

## License

CivicCast code here: Apache-2.0. Dependency: `timeline-state-resolver` (MIT).
