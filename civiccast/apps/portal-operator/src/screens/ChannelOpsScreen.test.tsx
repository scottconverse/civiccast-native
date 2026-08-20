// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { ChannelPlayoutPlan, ChannelProfile, EgressStateRow } from '../types/api.generated'
import { EgressControlPanel, PlayoutPlanPanel } from './ChannelOpsScreen'

afterEach(cleanup)

const CHANNEL = {
  channel_id: 'public',
  slug: 'public',
  kind: 'public',
  branding: { display_name: 'Public Channel' } as ChannelProfile['branding'],
  fallback_behavior: 'slate',
} as ChannelProfile

describe('PlayoutPlanPanel', () => {
  it('renders a block status through the shared vocabulary, not the raw enum', () => {
    // GauntletGate F1 wired this screen's StatusPill (line 93) through
    // stateLabel(), but no test here exercised that call site, so a revert
    // back to a bare `{label}` would have gone unnoticed. 'fallback' is a
    // real PlayoutBlock['status'] value; stateLabel sentence-cases it to
    // 'Fallback' -- if the wiring is reverted, the DOM shows the raw
    // lowercase enum word instead.
    const plan: ChannelPlayoutPlan = {
      generated_at: '2026-06-15T12:00:00Z',
      channel: CHANNEL,
      source: 'schedule-store',
      blocks: [
        {
          block_id: 'blk-1',
          channel_id: 'public',
          kind: 'live',
          title: 'Council meeting',
          starts_at: '2026-06-15T12:00:00Z',
          duration_seconds: 600,
          source_ref: 'src-1',
          status: 'fallback',
        },
      ],
      gap_blocks: [],
      export_formats: [],
      proof_boundary: 'schedule-to-playout contract',
      not_claimed: [],
    }
    const { getByText, queryByText } = render(<PlayoutPlanPanel plan={plan} />)
    expect(getByText('Fallback')).toBeTruthy()
    expect(queryByText('fallback')).toBeNull()
  })

  it('shows the loading placeholder before a plan has arrived', () => {
    const { container } = render(<PlayoutPlanPanel plan={undefined} />)
    expect(container.textContent).toContain('Loading schedule-to-playout plan...')
  })
})

function egressState(state: EgressStateRow['state']): EgressStateRow {
  return { channel_id: 'public', state, updated_at: '2026-05-31T18:00:00Z' }
}

function renderEgressPill(state: EgressStateRow['state']) {
  return render(
    <EgressControlPanel
      channelId="public"
      state={egressState(state)}
      health={[]}
      pendingCommand={null}
      canControl={false}
      error={null}
      onCommand={() => {}}
    />,
  )
}

describe('EgressControlPanel egress-state pill tone', () => {
  it('renders a not-on-air feed as attention-worthy amber, matching System Health', () => {
    // The verify caught this: STOPPED rendered blue (info) here while System
    // Health rendered it amber (warn) -- same feed, two colours. Both now route
    // through toneForEgressState, so this pill must be warn-soft, not info-soft.
    const { getByText } = renderEgressPill('STOPPED')
    const pill = getByText('Stopped')
    expect(pill.style.background).toBe('var(--cc-warn-soft)')
    expect(pill.style.background).not.toBe('var(--cc-info-soft)')
  })

  it('renders ON_AIR as ok and ERROR as err', () => {
    expect(renderEgressPill('ON_AIR').getByText('On air').style.background).toBe('var(--cc-ok-soft)')
    cleanup()
    expect(renderEgressPill('ERROR').getByText('Needs attention').style.background).toBe('var(--cc-err-soft)')
  })
})
