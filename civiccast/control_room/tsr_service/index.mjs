// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// CivicCast control-room TSR sidecar (S16). A small localhost HTTP service that
// embeds TSR (timeline-state-resolver, MIT) and exposes the CivicCast-owned
// contract the Python control plane calls. The Python plane is the only caller
// (bound to 127.0.0.1). No GPL/AGPL device-control code is linked here — TSR is
// MIT; OBS/vMix/ATEM/etc. are reached only over their own socket protocols by
// TSR, as separate processes.
//
// Contract (all JSON, 127.0.0.1 only):
//   GET  /healthz          -> {ok, tsr}                       liveness + TSR version
//   POST /probe-device     {device, profile} -> {reachable, capability_map, detail}
//   POST /apply-cue        {device, profile, action, payload} -> {ok, detail, device_state}
//
// The cue->timeline translation (buildCueState) is a PURE function exported for
// tests; it uses TSR's real DeviceType / TimelineContentTypeOBS / Mapping*Type
// enums. The OBS path is mapped precisely (the V1 lab-prove target + the
// universal device); other device kinds accept the cue payload as the TSR
// content body (the cue author targets the device). The live device connection
// + applying state to a REAL device is the rung-1 lab proof (LPM), not provable
// without the physical device.

import { createServer } from 'node:http';
import {
  Conductor,
  DeviceType,
  TimelineContentTypeOBS,
  MappingObsType,
} from 'timeline-state-resolver';

// CivicCast ProductionDevice.kind -> TSR DeviceType (verified against TSR 9.x exports).
const DEVICE_TYPE = {
  obs: DeviceType.OBS,
  vmix: DeviceType.VMIX,
  atem: DeviceType.ATEM,
  hyperdeck: DeviceType.HYPERDECK,
  casparcg: DeviceType.CASPARCG,
  ptz: DeviceType.VISCA_OVER_IP,
  osc: DeviceType.OSC,
  tcp: DeviceType.TCPSEND,
  http: DeviceType.HTTPSEND,
  // HONEST LABEL — do not "fix" this by faking a driver: 'gpi' and 'serial'
  // are network-relay triggers (TCP); direct GPI/serial hardware is not
  // supported in this release. TSR has no dedicated GPI-contact-closure or
  // serial (RS-232/422) device type, so both route through the generic
  // TCPSEND adapter (S18 gap-8 facility control) with the raw command as
  // payload. Audited as DeviceCommands on the CivicCast side. A station that
  // needs real hardware GPI/serial fronts it with its own TCP-to-GPI or
  // TCP-to-serial relay box — this TCP path already reaches it. See
  // ProductionDevice.kind's Field description (civiccast/control_room/
  // models.py) and CAPABILITIES.md for the same disclosure surfaced to
  // operators and API consumers.
  gpi: DeviceType.TCPSEND,
  serial: DeviceType.TCPSEND,
};

// OBS action -> (content type, mapping type, content fields). The friendly
// CivicCast cue actions for the V1 OBS target.
const OBS_ACTION = {
  scene: (p) => [
    TimelineContentTypeOBS.CURRENT_SCENE,
    MappingObsType.CurrentScene,
    { sceneName: p.scene },
  ],
  transition: (p) => [
    TimelineContentTypeOBS.CURRENT_TRANSITION,
    MappingObsType.CurrentTransition,
    { transitionName: p.transition ?? 'Cut' },
  ],
  // overlay push/clear toggles a scene item's visibility (a lower-third source).
  overlay_push: (p) => [
    TimelineContentTypeOBS.SCENE_ITEM,
    MappingObsType.SceneItem,
    { on: true, ...p },
  ],
  overlay_clear: (p) => [
    TimelineContentTypeOBS.SCENE_ITEM,
    MappingObsType.SceneItem,
    { on: false, ...p },
  ],
};

const LAYER = 'cue';

/**
 * Pure translation of a CivicCast cue into a TSR (timeline, mappings) pair for
 * conductor.setTimelineAndMappings. Exported for tests — no device, no I/O.
 */
export function buildCueState(deviceId, kind, action, payload) {
  const k = String(kind || '').toLowerCase();
  const deviceType = DEVICE_TYPE[k];
  if (deviceType === undefined) {
    throw new Error(`unsupported device kind: ${kind}`);
  }
  const p = payload || {};

  let content;
  let mappingType;
  if (deviceType === DeviceType.OBS && OBS_ACTION[action]) {
    const [type, mt, fields] = OBS_ACTION[action](p);
    content = { deviceType: DeviceType.OBS, type, ...fields };
    mappingType = mt;
  } else {
    // Generic path: the cue payload IS the TSR content body for this device
    // kind (the cue author targets the device). Validated at LPM per device.
    content = { deviceType, ...p };
    mappingType = p.mappingType;
  }

  const now = Date.now();
  const timeline = [
    {
      id: `${LAYER}_${now}`,
      enable: { start: now },
      layer: LAYER,
      content,
    },
  ];
  const mappings = {
    [LAYER]: {
      device: deviceType,
      deviceId,
      ...(mappingType !== undefined ? { mappingType } : {}),
      options: {},
    },
  };
  return { timeline, mappings };
}

function connectionConfig(deviceId, device) {
  const kind = String(device.kind || '').toLowerCase();
  const deviceType = DEVICE_TYPE[kind];
  if (deviceType === undefined) throw new Error(`unsupported device kind: ${device.kind}`);
  // options shape is per-device; the common host/port covers OBS/vMix/ATEM/etc.
  const options = { ...(device.options || {}) };
  if (device.host) options.host = device.host;
  if (device.port) options.port = device.port;
  if (device.secret) options.password = device.secret; // resolved by the Python caller
  return { deviceId, type: deviceType, options };
}

class TsrBridge {
  constructor() {
    this._conductor = null;
  }

  async _ready() {
    if (this._conductor) return this._conductor;
    const conductor = new Conductor();
    await conductor.init();
    this._conductor = conductor;
    return conductor;
  }

  async applyCue({ device, action, payload }) {
    const conductor = await this._ready();
    const deviceId = device.device_id || device.deviceId || 'cuedev';
    const cm = conductor.connectionManager;
    if (!cm.getConnection(deviceId)) {
      await cm.createConnection(connectionConfig(deviceId, device));
    }
    const { timeline, mappings } = buildCueState(
      deviceId, device.kind, action, payload,
    );
    conductor.setTimelineAndMappings(timeline, mappings);
    return { ok: true, detail: '', device_state: { action, layer: LAYER } };
  }

  async probeDevice({ device }) {
    const conductor = await this._ready();
    const deviceId = device.device_id || device.deviceId || 'probedev';
    const cm = conductor.connectionManager;
    if (!cm.getConnection(deviceId)) {
      await cm.createConnection(connectionConfig(deviceId, device));
    }
    const conn = cm.getConnection(deviceId);
    const reachable = Boolean(conn);
    return {
      reachable,
      capability_map: { device_type: String(device.kind) },
      detail: reachable ? '' : 'connection not established',
    };
  }
}

// --- HTTP server -------------------------------------------------------------

const bridge = new TsrBridge();

function send(res, status, body) {
  const buf = Buffer.from(JSON.stringify(body), 'utf-8');
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': buf.length });
  res.end(buf);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > 1_000_000) reject(new Error('payload too large'));
      else chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf-8')) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

const server = createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/healthz') {
      return send(res, 200, { ok: true, tsr: '9.3.2' });
    }
    if (req.method === 'POST' && req.url === '/probe-device') {
      const body = await readJson(req);
      return send(res, 200, await bridge.probeDevice(body));
    }
    if (req.method === 'POST' && req.url === '/apply-cue') {
      const body = await readJson(req);
      return send(res, 200, await bridge.applyCue(body));
    }
    return send(res, 404, { ok: false, detail: 'not found' });
  } catch (err) {
    // Never leak secrets/payloads — report the error type/message only.
    return send(res, 502, { ok: false, detail: String(err && err.message ? err.message : err) });
  }
});

// Only start the listener when run directly (not when imported by a test).
const RUN_DIRECTLY = import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1]?.endsWith('index.mjs');
if (RUN_DIRECTLY && !process.env.CIVICCAST_TSR_NO_LISTEN) {
  const port = Number(process.env.CIVICCAST_TSR_PORT || 7717);
  server.listen(port, '127.0.0.1', () => {
    process.stdout.write(`[control-room-tsr] listening on 127.0.0.1:${port}\n`);
  });
}

export { server, TsrBridge, DEVICE_TYPE };
