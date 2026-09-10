// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { headendApplyConfirm, type HeadendApplyPayload } from './headendConfirm'

// Review round 3 delta, MAJOR 1: the confirm dialog is the operator's consent.
// Applying a preset to a channel standing by on its slate restarts it, which
// terminates the one worker producing every output -- the cable headend feed
// included -- so the dialog must say so BEFORE the click, in every variant,
// and must never again promise that other outputs "keep running unchanged".
//
// Review round 4 delta, MINOR 2: the copy is pinned PER VARIANT. A single
// shared sentence pinned into all four is how "the cable feed drops for a few
// seconds" was locked into the one variant that deletes the cable feed (web
// preview + replace other outputs). Each case below states what that variant
// actually does to the cable feed.

const payload = (overrides: Partial<HeadendApplyPayload>): HeadendApplyPayload => ({
  profile_id: 'local-rehearsal-hls',
  destination_uri: '',
  muxrate_kbps: null,
  keep_existing_sinks: true,
  ...overrides,
})

const webKeep = payload({})
const webReplace = payload({ keep_existing_sinks: false })
const cableKeep = payload({ profile_id: 'generic-udp-spts' })
const cableReplace = payload({ profile_id: 'generic-udp-spts', keep_existing_sinks: false })

// The three variants after which a cable feed is still configured: the cable
// feed is interrupted by the rebuild and comes back.
const cableFeedSurvives: Array<[string, HeadendApplyPayload]> = [
  ['web preview, keep other outputs', webKeep],
  ['cable preset, keep other outputs', cableKeep],
  ['cable preset, replace other outputs', cableReplace],
]

const allVariants: Array<[string, HeadendApplyPayload]> = [
  ...cableFeedSurvives,
  ['web preview, replace other outputs', webReplace],
]

describe('headendApplyConfirm', () => {
  it.each(cableFeedSurvives)(
    '%s: says every output including cable drops on a slate restart',
    (_name, p) => {
      const confirm = headendApplyConfirm(p, 'Channel 12')
      expect(confirm.body).toContain('every output, including the cable feed, drops for a few seconds')
      expect(confirm.body).toContain('restarted right away')
      expect(confirm.body).not.toContain('do not come back')
    },
  )

  it('web preview, replace other outputs: says the cable feed is removed, not briefly dropped', () => {
    // keep_existing_sinks=false leaves [hls] -- the SRT/UDP headend sink is
    // deleted. "Drops for a few seconds" would be a lie here.
    const confirm = headendApplyConfirm(webReplace, 'Channel 12')
    expect(confirm.body).toContain("removes the channel's other outputs")
    expect(confirm.body).toContain(
      'the cable feed and every other output are removed and do not come back',
    )
    expect(confirm.body).toContain('only the web preview is configured afterwards')
    expect(confirm.body).toContain('the slate drops for a few seconds while the pipeline rebuilds')
    expect(confirm.body).toContain(
      'the cable feed ends and the web preview begins when you next Stop and Start the channel',
    )
    expect(confirm.body).not.toContain('every output, including the cable feed, drops')
  })

  it.each(allVariants)('%s: covers every channel state before the click', (_name, p) => {
    const confirm = headendApplyConfirm(p, 'Channel 12')
    // Standing by on its slate: restarted now.
    expect(confirm.body).toContain('If the channel is standing by on its slate, it is restarted right away')
    // A program on air: never interrupted by the apply itself.
    expect(confirm.body).toContain('If a program is on air, nothing is interrupted')
    expect(confirm.body).toContain('when you next Stop and Start the channel')
    // Stopped: the third state, which the shared sentence used to leave out.
    expect(confirm.body).toContain('If the channel is stopped, the change takes effect at its next start')
  })

  it.each(allVariants)('%s: never promises other outputs keep running unchanged', (_name, p) => {
    const confirm = headendApplyConfirm(p, 'Channel 12')
    expect(confirm.body).not.toMatch(/keep running/i)
    expect(confirm.body).not.toMatch(/keeps running/i)
    expect(confirm.body).not.toMatch(/unchanged/i)
  })

  it('names the channel and keeps the web-preview framing for the local preset', () => {
    const confirm = headendApplyConfirm(webKeep, 'Channel 12')
    expect(confirm.title).toBe('Enable web preview for this channel?')
    expect(confirm.confirmLabel).toBe('Enable web preview')
    expect(confirm.body).toContain('residents can watch Channel 12 in the portal')
    expect(confirm.body).toContain("cable and other outputs stay configured")
  })

  it('says other outputs are removed when the operator chose not to keep them', () => {
    const local = headendApplyConfirm(webReplace, 'Channel 12')
    expect(local.body).toContain("removes the channel's other outputs")
    const cable = headendApplyConfirm(cableReplace, 'Channel 12')
    expect(cable.title).toBe('Apply this headend preset?')
    expect(cable.confirmLabel).toBe('Apply preset')
    expect(cable.body).toContain("removes the channel's other outputs")
    expect(cable.body).toContain('only the headend feed is configured afterwards')
  })
})
