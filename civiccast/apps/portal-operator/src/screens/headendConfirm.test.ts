// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { headendApplyConfirm, type HeadendApplyPayload } from './headendConfirm'

// Review round 3 delta, MAJOR 1: the confirm dialog is the operator's consent.
// Applying a preset to a channel standing by on its slate restarts it, which
// terminates the one worker producing every output -- the cable headend feed
// included -- so the dialog must say so BEFORE the click, in every variant,
// and must never again promise that other outputs "keep running unchanged".

const payload = (overrides: Partial<HeadendApplyPayload>): HeadendApplyPayload => ({
  profile_id: 'local-rehearsal-hls',
  destination_uri: '',
  muxrate_kbps: null,
  keep_existing_sinks: true,
  ...overrides,
})

const variants: Array<[string, HeadendApplyPayload]> = [
  ['web preview, keep other outputs', payload({})],
  ['web preview, replace other outputs', payload({ keep_existing_sinks: false })],
  ['cable preset, keep other outputs', payload({ profile_id: 'generic-udp-spts' })],
  [
    'cable preset, replace other outputs',
    payload({ profile_id: 'generic-udp-spts', keep_existing_sinks: false }),
  ],
]

describe('headendApplyConfirm', () => {
  it.each(variants)('%s: says every output including cable drops on a slate restart', (_name, p) => {
    const confirm = headendApplyConfirm(p, 'Channel 12')
    expect(confirm.body).toContain('including the cable feed')
    expect(confirm.body).toContain('drops for a few seconds')
    expect(confirm.body).toContain('restarted right away')
    // ... and that a program on air is never interrupted by the apply itself.
    expect(confirm.body).toContain('If a program is on air, nothing is interrupted')
  })

  it.each(variants)('%s: never promises other outputs keep running unchanged', (_name, p) => {
    const confirm = headendApplyConfirm(p, 'Channel 12')
    expect(confirm.body).not.toMatch(/keep running/i)
    expect(confirm.body).not.toMatch(/keeps running/i)
    expect(confirm.body).not.toMatch(/unchanged/i)
  })

  it('names the channel and keeps the web-preview framing for the local preset', () => {
    const confirm = headendApplyConfirm(payload({}), 'Channel 12')
    expect(confirm.title).toBe('Enable web preview for this channel?')
    expect(confirm.confirmLabel).toBe('Enable web preview')
    expect(confirm.body).toContain('residents can watch Channel 12 in the portal')
    expect(confirm.body).toContain("cable and other outputs stay configured")
  })

  it('says other outputs are removed when the operator chose not to keep them', () => {
    const local = headendApplyConfirm(payload({ keep_existing_sinks: false }), 'Channel 12')
    expect(local.body).toContain("removes the channel's other outputs")
    const cable = headendApplyConfirm(
      payload({ profile_id: 'generic-udp-spts', keep_existing_sinks: false }),
      'Channel 12',
    )
    expect(cable.title).toBe('Apply this headend preset?')
    expect(cable.confirmLabel).toBe('Apply preset')
    expect(cable.body).toContain("removes the channel's other outputs")
  })
})
