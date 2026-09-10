// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type {
  ChannelNowNext,
  ChannelPlayoutPlan,
  ChannelProfile,
  ChannelProofLog,
  EgressStateRow,
  GraphicsOverlayStateResponse,
} from '../types/api.generated'
import { ApiError, type EgressHealthSample } from '../api/client'
import {
  EgressControlPanel,
  GraphicsOverlayPanel,
  PlayoutPanel,
  PlayoutPlanPanel,
  ProofPanel,
  START_WITHOUT_CONFIG_REASON,
} from './ChannelOpsScreen'

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

describe('EgressControlPanel captions row', () => {
  const sample: EgressHealthSample = {
    channel_id: 'public',
    sampled_at: '2026-06-15T12:00:00Z',
    state: 'ON_AIR',
    sink_connected: { head: true },
            dropped_frames: 0,
            seconds_on_air: 30,
    caption_status: 'not-verified',
  }

  function renderCaptions(liveCaptionsEnabled: boolean | undefined) {
    return render(
      <EgressControlPanel
        channelId="public"
        state={egressState('ON_AIR')}
        health={[sample]}
        pendingCommand={null}
        canControl={false}
        error={null}
        onCommand={() => {}}
        liveCaptionsEnabled={liveCaptionsEnabled}
      />,
    )
  }

  it('says the switch is off instead of waiting for a check that cannot pass', () => {
    const { container } = renderCaptions(false)
    expect(container.textContent).toContain('Off (switched off in the station profile)')
    expect(container.textContent).not.toContain('Not yet confirmed')
  })

  it('keeps the fail-closed wording while the switch is on or unknown', () => {
    expect(renderCaptions(true).container.textContent).toContain('Not yet confirmed (waiting for the on-air check)')
    cleanup()
    expect(renderCaptions(undefined).container.textContent).toContain('Not yet confirmed (waiting for the on-air check)')
  })
})

// beta.5 walkthrough F-27: Channels used to render sample-contract rows
// ("Public live programming -- Playing", "Captions: Attached") on a channel
// whose feed was Stopped. The API now reports nulls/empties until something
// real exists, and these panels must say so in plain words.
describe('PlayoutPanel honest empty states (F-27)', () => {
  it('says "No program on air" and "Nothing scheduled" when both slots are null', () => {
    const nowNext: ChannelNowNext = {
      generated_at: '2026-06-15T12:00:00Z',
      channel: CHANNEL,
      current: null,
      next: null,
      fallback_active: false,
      proof_boundary: 'egress-state-and-schedule-store',
    }
    const { getByText, queryByText } = render(<PlayoutPanel nowNext={nowNext} />)
    expect(getByText('No program on air')).toBeTruthy()
    expect(getByText('Nothing scheduled')).toBeTruthy()
    expect(queryByText(/live programming/)).toBeNull()
    expect(queryByText('Playing')).toBeNull()
  })

  it('renders a real on-air block in the Now slot and still says Nothing scheduled for Next', () => {
    const nowNext: ChannelNowNext = {
      generated_at: '2026-06-15T12:00:00Z',
      channel: CHANNEL,
      current: {
        block_id: 'public-egress-on_air',
        channel_id: 'public',
        kind: 'live',
        title: 'Council chamber camera',
        starts_at: '2026-06-15T11:55:00Z',
        duration_seconds: 300,
        source_ref: 'Council chamber camera',
        status: 'playing',
      },
      next: null,
      fallback_active: false,
      proof_boundary: 'egress-state-and-schedule-store',
    }
    const { getByText, queryByText } = render(<PlayoutPanel nowNext={nowNext} />)
    expect(getByText('Council chamber camera')).toBeTruthy()
    expect(getByText('Playing')).toBeTruthy()
    expect(queryByText('No program on air')).toBeNull()
    expect(getByText('Nothing scheduled')).toBeTruthy()
  })
})

describe('PlayoutPlanPanel honest empty state (F-27)', () => {
  it('says "Nothing scheduled" for an empty schedule-store plan', () => {
    const plan: ChannelPlayoutPlan = {
      generated_at: '2026-06-15T12:00:00Z',
      channel: CHANNEL,
      source: 'schedule-store',
      blocks: [],
      gap_blocks: [],
      export_formats: ['json'],
      proof_boundary: 'software-schedule-to-playout-plan',
      not_claimed: [],
    }
    const { getByText, queryByText } = render(<PlayoutPlanPanel plan={plan} />)
    expect(getByText('Nothing scheduled')).toBeTruthy()
    expect(queryByText(/channel slate/)).toBeNull()
    expect(queryByText('Loading schedule-to-playout plan...')).toBeNull()
  })
})

describe('ProofPanel honest empty state (F-27)', () => {
  const emptyProof: ChannelProofLog = {
    generated_at: '2026-06-15T12:00:00Z',
    channel: CHANNEL,
    events: [],
    export_formats: ['json', 'csv-ready'],
    not_claimed: ['SDI or DeckLink output'],
  }

  it('says "No proof events yet" and hides the empty table', () => {
    const { getByText, queryByText, container } = render(<ProofPanel proof={emptyProof} />)
    expect(getByText('No proof events yet')).toBeTruthy()
    expect(queryByText('Attached')).toBeNull()
    const table = container.querySelector('table')
    expect(table?.closest('[hidden]')).toBeTruthy()
  })

  it('renders a daemon proof event with captions "Not verified", never "Attached", when unproven', () => {
    const proof: ChannelProofLog = {
      ...emptyProof,
      events: [
        {
          event_id: 'proof-1',
          observed_at: '2026-06-15T12:00:00Z',
          channel_id: 'public',
          scheduled_block_id: null,
          actual_kind: 'live',
          actual_status: 'playing',
          title: 'Council chamber camera',
          source_ref: 'Council chamber camera',
          failover_from: null,
          failover_reason: null,
          captions_attached: null,
          machine_summary: 'public:ON_AIR:chamber',
        },
      ],
    }
    const { getByText, queryByText } = render(<ProofPanel proof={proof} />)
    expect(getByText('Council chamber camera')).toBeTruthy()
    expect(getByText('Not verified')).toBeTruthy()
    expect(queryByText('Attached')).toBeNull()
    expect(queryByText('No proof events yet')).toBeNull()
  })
})

// beta.5 walkthrough F-29: Start was enabled (and accepted with 202) on a
// channel with no outgoing-feed configuration; the daemon dropped it and the
// state stayed Stopped with no reason shown.
describe('EgressControlPanel Start gating (F-29)', () => {
  function renderPanel(props: Partial<Parameters<typeof EgressControlPanel>[0]> = {}) {
    return render(
      <EgressControlPanel
        channelId="public"
        state={egressState('STOPPED')}
        health={[]}
        pendingCommand={null}
        canControl
        error={null}
        onCommand={() => {}}
        {...props}
      />,
    )
  }

  it('disables Start with the inline reason when the channel has no egress configuration', () => {
    const onCommand = vi.fn()
    const { getByRole, getByText } = renderPanel({ configured: false, onCommand })
    const start = getByRole('button', { name: 'Start' }) as HTMLButtonElement
    expect(start.disabled).toBe(true)
    expect(getByText(START_WITHOUT_CONFIG_REASON)).toBeTruthy()
    expect(start.getAttribute('aria-describedby')).toBe('egress-start-reason')
    fireEvent.click(start)
    expect(onCommand).not.toHaveBeenCalled()
    // Stop stays available: it is a harmless no-op the daemon accepts.
    expect((getByRole('button', { name: 'Stop' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('keeps Start disabled with a checking notice until the configuration list has loaded', () => {
    const { getByRole, getByText } = renderPanel({ configured: undefined })
    expect((getByRole('button', { name: 'Start' }) as HTMLButtonElement).disabled).toBe(true)
    expect(getByText('Checking for an outgoing-feed configuration...')).toBeTruthy()
  })

  it('enables Start once a configuration exists', () => {
    const onCommand = vi.fn()
    const { getByRole, queryByText } = renderPanel({ configured: true, onCommand })
    const start = getByRole('button', { name: 'Start' }) as HTMLButtonElement
    expect(start.disabled).toBe(false)
    expect(queryByText(START_WITHOUT_CONFIG_REASON)).toBeNull()
    fireEvent.click(start)
    expect(onCommand).toHaveBeenCalledWith('start')
  })

  it('surfaces a not-applied alert when the daemon never left Stopped after a queued Start', () => {
    const { getByRole } = renderPanel({
      configured: true,
      startNotApplied: { channelId: 'public', waitedSeconds: 20 },
    })
    const alert = getByRole('alert')
    expect(alert.textContent).toContain('Start was queued but the feed did not start.')
    expect(alert.textContent).toContain('within 20s')
  })

  it('shows the API 409 reason when the router refuses the start', () => {
    const { getByRole } = renderPanel({
      configured: true,
      error: new ApiError(
        'Conflict',
        409,
        'No outgoing-feed configuration for public. Apply a headend preset or the local rehearsal preset first.',
      ),
    })
    expect(getByRole('alert').textContent).toContain('No outgoing-feed configuration for public.')
  })
})
