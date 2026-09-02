// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { ChannelProfile, RouterInventory, StaffIdentityResponse, VirtualRouterPanel } from '../types/api.generated'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getFacilityRouterInventory: vi.fn(),
  getFacilityRouterPanel: vi.fn(),
  getStaffIdentity: vi.fn(),
  listChannelProfiles: vi.fn(),
  previewOverlayCompositorPlan: vi.fn(),
  previewFacilityRouterSchedulePlan: vi.fn(),
  previewFacilityRouterTake: vi.fn(),
}))

import {
  ApiError,
  getFacilityRouterInventory,
  getFacilityRouterPanel,
  getStaffIdentity,
  listChannelProfiles,
  previewOverlayCompositorPlan,
  previewFacilityRouterSchedulePlan,
  previewFacilityRouterTake,
} from '../api/client'
import {
  ChannelPicker,
  FacilityRouterScreen,
  OverlayPlanPanel,
  ScheduledTakePanel,
} from './FacilityRouterScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return {
    operator_id: 'op-1',
    operator_display_name: 'Operator',
    roles,
  } as StaffIdentityResponse
}

function channel(overrides: Partial<ChannelProfile> = {}): ChannelProfile {
  return {
    channel_id: 'government',
    slug: 'government',
    kind: 'government',
    branding: { display_name: 'Government Channel', short_name: 'Gov', color: '#123456', logo_text: 'G' } as ChannelProfile['branding'],
    fallback_behavior: 'slate',
    ...overrides,
  }
}

function inventory(overrides: Partial<RouterInventory> = {}): RouterInventory {
  return {
    generated_at: '2026-08-01T00:00:00Z',
    endpoints: [
      {
        endpoint_id: 'ep-1',
        label: 'Main videohub',
        vendor: 'blackmagic-design',
        protocol: 'blackmagic-videohub',
        transport: 'tcp',
        host: '10.0.0.5',
        port: 9990,
        enabled: true,
      },
    ],
    sources: [
      { input_id: 'src-1', label: 'Council camera 1', physical_port: '1', enabled: true },
    ],
    destinations: [
      { output_id: 'dst-1', label: 'Program out', physical_port: '1', enabled: true },
    ],
    proof_boundary: 'facility router preview only',
    ...overrides,
  }
}

function panel(): VirtualRouterPanel {
  return {
    panel_id: 'panel-1',
    endpoint_id: 'ep-1',
    label: 'Virtual panel',
    mobile_columns: 2,
    buttons: [],
  } as VirtualRouterPanel
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FacilityRouterScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getFacilityRouterInventory).mockResolvedValue(inventory())
  vi.mocked(getFacilityRouterPanel).mockResolvedValue(panel())
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
  vi.mocked(listChannelProfiles).mockResolvedValue([channel()])
  vi.mocked(previewFacilityRouterTake).mockResolvedValue({
    request_id: 'req-1',
    endpoint_id: 'ep-1',
    vendor: 'blackmagic-design',
    protocol: 'blackmagic-videohub',
    transport: 'tcp',
    source_label: 'Council camera 1',
    destination_label: 'Program out',
    target: '10.0.0.5:9990',
    command_preview: 'CROSSPOINT 1 1',
    ready_to_send: true,
    operator_action: 'Confirm on the physical router.',
    proof_boundary: 'facility router preview only',
  } as never)
  vi.mocked(previewOverlayCompositorPlan).mockResolvedValue({
    ordered_layers: [{ kind: 'squeezeback' }, { kind: 'l-bar' }],
    ffmpeg_args: ['-c:v', 'libx264'],
    filter_complex: 'overlay=...',
    gpu_accelerated: false,
    acceleration_mode: 'cpu',
    proof_boundary: 'overlay preview only',
  } as never)
  vi.mocked(previewFacilityRouterSchedulePlan).mockResolvedValue({
    request_id: 'req-sched-1',
    schedule_item_id: 'operator-preview-schedule',
    channel_id: 'government',
    starts_at: '2026-08-01T12:00:00Z',
    scheduled_take_at: '2026-08-01T11:59:45Z',
    preroll_seconds: 15,
    take_plan: { command_preview: 'CROSSPOINT 1 1' },
    automatic_take_ready: true,
    operator_action: 'Nothing to confirm yet.',
    proof_boundary: 'schedule preview only',
  } as never)
})

// --- State 1: no channels configured ---------------------------------------

describe('FacilityRouterScreen with no configured channels', () => {
  it('shows the no-channels message and disables scheduled take / overlay actions', async () => {
    vi.mocked(listChannelProfiles).mockResolvedValue([])
    const { findAllByText, getByText } = renderScreen()

    await findAllByText(/No channels are configured yet\./)

    const scheduleButton = getByText('Preview scheduled take') as HTMLButtonElement
    const overlayButton = getByText('Preview L-bar and squeezeback') as HTMLButtonElement
    expect(scheduleButton.disabled).toBe(true)
    expect(overlayButton.disabled).toBe(true)
  })
})

// --- State 2: exactly one channel (auto-selected but shown) ----------------

describe('FacilityRouterScreen with exactly one configured channel', () => {
  it('auto-selects the channel, shows it in the picker, and enables the actions', async () => {
    vi.mocked(listChannelProfiles).mockResolvedValue([channel({ channel_id: 'government' })])
    const { findByDisplayValue, getByText } = renderScreen()

    const select = (await findByDisplayValue('Government Channel (government)')) as HTMLSelectElement
    expect(select.value).toBe('government')

    await waitFor(() => {
      expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(false)
      expect((getByText('Preview L-bar and squeezeback') as HTMLButtonElement).disabled).toBe(false)
    })
  })
})

// --- State 3: multiple channels require an explicit pick -------------------

describe('FacilityRouterScreen with multiple configured channels', () => {
  it('does not auto-select, blocks channel-dependent actions until the operator picks one, then carries the picked id through', async () => {
    vi.mocked(listChannelProfiles).mockResolvedValue([
      channel({ channel_id: 'government', branding: { display_name: 'Government Channel' } as ChannelProfile['branding'] }),
      channel({ channel_id: 'community', branding: { display_name: 'Community Channel' } as ChannelProfile['branding'] }),
    ])
    const { findByText, getByLabelText, getByText } = renderScreen()

    await findByText('Choose a channel before scheduling a take.')
    const scheduleButton = getByText('Preview scheduled take') as HTMLButtonElement
    const overlayButton = getByText('Preview L-bar and squeezeback') as HTMLButtonElement
    expect(scheduleButton.disabled).toBe(true)
    expect(overlayButton.disabled).toBe(true)

    const select = getByLabelText('Target channel') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'community' } })

    await waitFor(() => {
      expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(false)
    })

    fireEvent.click(getByText('Preview L-bar and squeezeback'))
    await waitFor(() => {
      expect(vi.mocked(previewOverlayCompositorPlan)).toHaveBeenCalled()
    })
    const overlayArgs = vi.mocked(previewOverlayCompositorPlan).mock.calls[0][0]
    expect(overlayArgs.channel_id).toBe('community')
    expect(overlayArgs.input_url).toContain('community')
    expect(overlayArgs.output_manifest_path).toContain('community')

    // Manual crosspoint preview never gains a channel contract.
    fireEvent.click(getByText('Preview take'))
    await waitFor(() => {
      expect(vi.mocked(previewFacilityRouterTake)).toHaveBeenCalled()
    })
    const manualArgs = vi.mocked(previewFacilityRouterTake).mock.calls[0][0]
    expect(manualArgs).not.toHaveProperty('channel_id')
  })
})

// --- State 4: stale selection (channel removed) -----------------------------

describe('FacilityRouterScreen when the selected channel disappears', () => {
  it('clears the selection and stale preview data, and surfaces a notice', async () => {
    vi.mocked(listChannelProfiles).mockResolvedValue([channel({ channel_id: 'government' })])
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { findByDisplayValue, getByText, queryByText } = render(
      <QueryClientProvider client={qc}>
        <FacilityRouterScreen />
      </QueryClientProvider>,
    )

    await findByDisplayValue('Government Channel (government)')
    fireEvent.click(getByText('Preview L-bar and squeezeback'))
    await waitFor(() => {
      expect(getByText(/Layer order:/)).toBeTruthy()
    })

    // The channel is removed from the configured list (e.g. deleted in Channel Ops).
    vi.mocked(listChannelProfiles).mockResolvedValue([])
    await qc.invalidateQueries({ queryKey: ['channel-profiles'] })

    await waitFor(() => {
      expect(getByText(/is no longer configured\. Choose another channel\./)).toBeTruthy()
    })
    // The stale overlay preview is cleared, not left on screen against a channel that no longer exists.
    expect(queryByText(/Layer order:/)).toBeNull()
    expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(true)
  })
})

// --- State 5: channel list load error ---------------------------------------

describe('FacilityRouterScreen when the channel list fails to load', () => {
  it('shows a load-error message and disables channel-dependent actions without hiding the rest of the page', async () => {
    vi.mocked(listChannelProfiles).mockRejectedValue(new ApiError('offline', 0, 'Service unavailable.'))
    const { findByText, getByText } = renderScreen()

    await findByText('Service unavailable.')
    expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(true)
    expect((getByText('Preview L-bar and squeezeback') as HTMLButtonElement).disabled).toBe(true)
    // The rest of the page (router endpoints, manual crosspoint) still renders.
    expect(getByText('Router endpoints')).toBeTruthy()
    expect(getByText('Manual crosspoint')).toBeTruthy()
  })
})

// --- State 6: permissions (read-only role) ----------------------------------

describe('FacilityRouterScreen for an operator without the meeting_operator role', () => {
  it('disables scheduled take and overlay actions with a role-specific message, but keeps manual preview available', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listChannelProfiles).mockResolvedValue([channel({ channel_id: 'government' })])
    const { findByDisplayValue, getAllByText, getByText } = renderScreen()

    await findByDisplayValue('Government Channel (government)')

    await waitFor(() => {
      expect(getAllByText(/require the meeting operator role/).length).toBeGreaterThan(0)
    })
    expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(true)
    expect((getByText('Preview L-bar and squeezeback') as HTMLButtonElement).disabled).toBe(true)
    // Manual crosspoint preview is facility-path scoped and stays available.
    const manualButton = getByText('Preview take') as HTMLButtonElement
    expect(manualButton.disabled).toBe(false)
  })
})

// --- State 7: mobile layout ---------------------------------------------------

describe('FacilityRouterScreen on a mobile viewport', () => {
  it('keeps the channel picker and channel-dependent actions reachable, and the virtual panel honors mobile_columns', async () => {
    Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true })
    vi.mocked(getFacilityRouterPanel).mockResolvedValue({
      panel_id: 'panel-1',
      endpoint_id: 'ep-1',
      label: 'Virtual panel',
      mobile_columns: 1,
      buttons: [
        {
          button_id: 'btn-1',
          label: 'Camera 1 to Program',
          source_id: 'src-1',
          destination_id: 'dst-1',
          enabled: true,
          operator_action: 'Confirm on the physical router.',
        },
      ],
    } as VirtualRouterPanel)
    vi.mocked(listChannelProfiles).mockResolvedValue([channel({ channel_id: 'government' })])

    const { findByDisplayValue, findByText, getByText } = renderScreen()

    await findByDisplayValue('Government Channel (government)')
    const virtualButton = await findByText('Camera 1 to Program')
    // Confirm the panel actually used the single-column mobile layout, not a
    // desktop default -- proves the grid isn't just decorated but wired to
    // panel.mobile_columns regardless of viewport width.
    const grid = getByText('Camera 1 to Program').closest('div[class*="grid"]') as HTMLElement
    expect(grid.style.gridTemplateColumns).toContain('repeat(1,')
    expect(virtualButton).toBeTruthy()

    expect((getByText('Preview scheduled take') as HTMLButtonElement).disabled).toBe(false)
    expect((getByText('Preview L-bar and squeezeback') as HTMLButtonElement).disabled).toBe(false)
  })
})

// --- Unit coverage for the extracted, exported sub-components ---------------

describe('ChannelPicker', () => {
  it('renders the load-error banner using the ApiError detail', () => {
    const { getByText } = render(
      <ChannelPicker
        channels={[]}
        selectedChannelId=""
        isLoading={false}
        loadError={new ApiError('x', 0, 'Channels endpoint is down.')}
        staleNotice={null}
        onSelect={() => {}}
      />,
    )
    expect(getByText('Channels endpoint is down.')).toBeTruthy()
  })

  it('renders the stale-selection notice', () => {
    const { getByText } = render(
      <ChannelPicker
        channels={[]}
        selectedChannelId=""
        isLoading={false}
        loadError={null}
        staleNotice="The previously selected channel (government) is no longer configured. Choose another channel."
        onSelect={() => {}}
      />,
    )
    expect(getByText(/is no longer configured\. Choose another channel\./)).toBeTruthy()
  })
})

describe('ScheduledTakePanel / OverlayPlanPanel disabled reasons', () => {
  it('disables the scheduled-take button and shows the reason text', () => {
    const { getByText } = render(
      <ScheduledTakePanel
        plan={null}
        busy={false}
        error={null}
        disabledReason="Choose a channel before scheduling a take."
        onPreview={() => {}}
      />,
    )
    const button = getByText('Preview scheduled take') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(getByText('Choose a channel before scheduling a take.')).toBeTruthy()
  })

  it('disables the overlay button and shows the reason text', () => {
    const { getByText } = render(
      <OverlayPlanPanel
        plan={null}
        busy={false}
        error={null}
        disabledReason="Choose a channel before previewing an overlay."
        onPreview={() => {}}
      />,
    )
    const button = getByText('Preview L-bar and squeezeback') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(getByText('Choose a channel before previewing an overlay.')).toBeTruthy()
  })

  it('enables both buttons and hides the reason text once a channel is selected', () => {
    const onPreview = vi.fn()
    const { getByText, queryByText } = render(
      <ScheduledTakePanel plan={null} busy={false} error={null} disabledReason={null} onPreview={onPreview} />,
    )
    const button = getByText('Preview scheduled take') as HTMLButtonElement
    expect(button.disabled).toBe(false)
    expect(queryByText('Choose a channel before scheduling a take.')).toBeNull()
    fireEvent.click(button)
    expect(onPreview).toHaveBeenCalledTimes(1)
  })
})
