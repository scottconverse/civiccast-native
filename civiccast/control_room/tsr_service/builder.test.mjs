// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Verifies the pure cue->timeline builder against TSR's REAL enums (no device).
// Run: CIVICCAST_TSR_NO_LISTEN=1 node --test  (needs `npm install` first).

import test from 'node:test';
import assert from 'node:assert/strict';
import { buildCueState, DEVICE_TYPE, server } from './index.mjs';

test('OBS scene cue uses the real TSR OBS content + mapping enums', () => {
  const s = buildCueState('dev1', 'obs', 'scene', { scene: 'CAM2' });
  assert.equal(s.timeline.length, 1);
  assert.equal(s.timeline[0].layer, 'cue');
  assert.equal(s.timeline[0].content.deviceType, 'OBS');
  assert.equal(s.timeline[0].content.type, 'CURRENT_SCENE');
  assert.equal(s.timeline[0].content.sceneName, 'CAM2');
  assert.equal(s.mappings.cue.device, 'OBS');
  assert.equal(s.mappings.cue.deviceId, 'dev1');
  assert.equal(s.mappings.cue.mappingType, 'currentScene');
});

test('OBS transition cue maps to CURRENT_TRANSITION', () => {
  const s = buildCueState('d', 'obs', 'transition', { transition: 'Fade' });
  assert.equal(s.timeline[0].content.type, 'CURRENT_TRANSITION');
  assert.equal(s.timeline[0].content.transitionName, 'Fade');
});

test('a non-OBS device passes the cue payload through as TSR content', () => {
  const s = buildCueState('d2', 'vmix', 'input', { input: 5 });
  assert.equal(s.timeline[0].content.deviceType, 'VMIX');
  assert.equal(s.timeline[0].content.input, 5);
  assert.equal(s.mappings.cue.device, 'VMIX');
});

test('every CivicCast device kind maps to a real TSR DeviceType', () => {
  for (const kind of ['obs', 'vmix', 'atem', 'hyperdeck', 'casparcg', 'ptz', 'osc', 'tcp', 'http', 'gpi', 'serial']) {
    assert.notEqual(DEVICE_TYPE[kind], undefined, `missing TSR DeviceType for ${kind}`);
  }
});

test('unknown device kind is rejected', () => {
  assert.throws(() => buildCueState('d', 'bogus', 'x', {}), /unsupported device kind/);
});

test('GET /healthz responds ok over a real socket', async () => {
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const { port } = server.address();
    const resp = await fetch(`http://127.0.0.1:${port}/healthz`);
    assert.equal(resp.status, 200);
    const body = await resp.json();
    assert.equal(body.ok, true);
    assert.ok(body.tsr);
  } finally {
    await new Promise((r) => server.close(r));
  }
});
