// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type {
  ChannelPlayoutPlan,
  ChannelProfile,
  EgressStateRow,
  GraphicsOverlayStateResponse,
} from '../types/api.generated'
import { EgressControlPanel, GraphicsOverlayPanel, PlayoutPlanPanel } from './ChannelOpsScreen'

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

function graphicsOverlayState(overrides: Partial<GraphicsOverlayStateResponse> = {}): GraphicsOverlayStateResponse {
  return {
    channel_id: 'public',
    graphics_overlay_enabled: false,
    graphics_overlay_lower_third_text: '',
    ...overrides,
  }
}

describe('GraphicsOverlayPanel', () => {
  // WP-11 item 2 (audit UX-007): pin the help copy so it can't regress back
  // to "station bug graphics overlay" (a different broadcast graphic from
  // the lower-third this control actually edits) and stays explicit that
  // the change lands on the channel's next pipeline build or a scheduled
  // swap, never as a hot-change to an already-live pipeline.
  it('explains next-build/scheduled-swap timing and never says "station bug"', () => {
    const { getByText, queryByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState()}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={() => {}}
      />,
    )
    expect(
      getByText(
        'Changes this channel’s lower-third banner on the next pipeline build or scheduled swap. It does not hot-change an already-live pipeline.',
      ),
    ).toBeTruthy()
    expect(queryByText(/station bug/i)).toBeNull()
  })

  it('reflects the returned/persisted enabled state in the toggle and badge', () => {
    const { getByText, getByDisplayValue, queryByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState({ graphics_overlay_enabled: true, graphics_overlay_lower_third_text: 'Town Council -- Live' })}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={() => {}}
      />,
    )
    expect(getByText('On air')).toBeTruthy()
    expect(getByText('Take off air')).toBeTruthy()
    expect(queryByText('Put on air')).toBeNull()
    expect(getByDisplayValue('Town Council -- Live')).toBeTruthy()
  })

  it('shows Off air and Put on air when the state is disabled', () => {
    const { getByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState()}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={() => {}}
      />,
    )
    expect(getByText('Off air')).toBeTruthy()
    expect(getByText('Put on air')).toBeTruthy()
  })

  it('requires a two-step confirm before calling the endpoint to change on-air state', () => {
    const onSave = vi.fn()
    const { getByText, getByPlaceholderText, queryByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState()}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={onSave}
      />,
    )
    fireEvent.change(getByPlaceholderText('e.g. Town Council -- Live'), {
      target: { value: 'Breaking: Council votes tonight' },
    })
    fireEvent.click(getByText('Put on air'))
    // First click only reveals the confirm row -- the endpoint is not called yet.
    expect(onSave).not.toHaveBeenCalled()
    expect(getByText('Confirm: put on air')).toBeTruthy()

    fireEvent.click(getByText('Confirm: put on air'))
    expect(onSave).toHaveBeenCalledWith({
      graphics_overlay_enabled: true,
      graphics_overlay_lower_third_text: 'Breaking: Council votes tonight',
    })
    expect(queryByText('Confirm: put on air')).toBeNull()
  })

  it('cancelling the confirm row does not call the endpoint', () => {
    const onSave = vi.fn()
    const { getByText, getByPlaceholderText, queryByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState({ graphics_overlay_enabled: true, graphics_overlay_lower_third_text: 'x' })}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={onSave}
      />,
    )
    fireEvent.click(getByText('Take off air'))
    expect(getByText('Confirm: take off air')).toBeTruthy()
    fireEvent.click(getByText('Cancel'))
    expect(queryByText('Confirm: take off air')).toBeNull()
    expect(onSave).not.toHaveBeenCalled()
    // Cancelling stays on air -- placeholder input untouched, still exists.
    expect(getByPlaceholderText('e.g. Town Council -- Live')).toBeTruthy()
  })

  it('disables Put on air until the operator enters banner text', () => {
    const { getByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState()}
        loadError={null}
        saving={false}
        canEdit
        saveError={null}
        onSave={() => {}}
      />,
    )
    const button = getByText('Put on air') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(getByText('Enter banner text before putting it on air.')).toBeTruthy()
  })

  it('disables editing when the operator lacks the role', () => {
    const { getByText } = render(
      <GraphicsOverlayPanel
        channelId="public"
        state={graphicsOverlayState()}
        loadError={null}
        saving={false}
        canEdit={false}
        saveError={null}
        onSave={() => {}}
      />,
    )
    expect(getByText(/requires the meeting operator or setup admin role/)).toBeTruthy()
    const button = getByText('Put on air') as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })
})
