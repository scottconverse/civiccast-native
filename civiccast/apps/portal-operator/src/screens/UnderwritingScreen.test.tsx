// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  SpotFlight,
  SpotPlacement,
  StaffIdentityResponse,
  UnderwriterAffidavit,
  UnderwritingSpot,
} from '../types/api.generated'

afterEach(cleanup)

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
  getStaffIdentity: vi.fn(),
  listUnderwritingSpots: vi.fn(),
  createUnderwritingSpot: vi.fn(),
  patchUnderwritingSpot: vi.fn(),
  deleteUnderwritingSpot: vi.fn(),
  listSpotFlights: vi.fn(),
  createSpotFlight: vi.fn(),
  patchSpotFlight: vi.fn(),
  deleteSpotFlight: vi.fn(),
  listSpotPlacements: vi.fn(),
  getUnderwriterAffidavit: vi.fn(),
  affidavitExportUrl: vi.fn(),
}))

import {
  affidavitExportUrl,
  createUnderwritingSpot,
  deleteUnderwritingSpot,
  getStaffIdentity,
  getUnderwriterAffidavit,
  listSpotFlights,
  listSpotPlacements,
  listUnderwritingSpots,
} from '../api/client'
import { UnderwritingScreen } from './UnderwritingScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'sam', operator_display_name: 'Sam', roles } as StaffIdentityResponse
}

function spot(overrides: Partial<UnderwritingSpot> = {}): UnderwritingSpot {
  return {
    spot_id: 'acme-15s',
    station_id: 'civiccast-station',
    underwriter: 'Acme Co-op',
    asset_id: 'asset-acme-ack',
    fcc_compliant_ack: true,
    review_notes: 'Reviewed by SC on 2026-06-18.',
    ...overrides,
  }
}

function flight(overrides: Partial<SpotFlight> = {}): SpotFlight {
  return {
    flight_id: 'acme-q3',
    spot_id: 'acme-15s',
    start_date: '2026-07-01',
    end_date: '2026-09-30',
    frequency_cap_per_day: 6,
    daypart_block_id: 'prime-evening',
    channels: ['gov-1', 'pub-1'],
    ...overrides,
  }
}

function placement(overrides: Partial<SpotPlacement> = {}): SpotPlacement {
  return {
    placement_id: 'pl-1',
    flight_id: 'acme-q3',
    channel_id: 'pub-1',
    scheduled_at: '2026-07-15T19:30:00Z',
    schedule_item_id: 'si-1',
    ...overrides,
  }
}

function affidavit(overrides: Partial<UnderwriterAffidavit> = {}): UnderwriterAffidavit {
  return {
    station_id: 'civiccast-station',
    underwriter: 'Acme Co-op',
    period_start: '2026-07-01',
    period_end: '2026-07-31',
    aired: [
      {
        spot_id: 'acme-15s',
        asset_id: 'asset-acme-ack',
        channel_id: 'pub-1',
        aired_at: '2026-07-15T19:30:00Z',
        duration_s: 15,
        placement_id: 'pl-1',
      },
    ],
    total_airings: 1,
    total_seconds: 15,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <UnderwritingScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(
    identity(['publish_operator', 'setup_admin', 'support_admin']),
  )
  vi.mocked(listUnderwritingSpots).mockResolvedValue([spot()])
  vi.mocked(listSpotFlights).mockResolvedValue([flight()])
  vi.mocked(listSpotPlacements).mockResolvedValue([placement()])
  vi.mocked(getUnderwriterAffidavit).mockResolvedValue(affidavit())
  vi.mocked(createUnderwritingSpot).mockResolvedValue(spot())
  vi.mocked(deleteUnderwritingSpot).mockResolvedValue(undefined)
  vi.mocked(affidavitExportUrl).mockImplementation((p) => {
    const sp = new URLSearchParams()
    sp.set('underwriter', p.underwriter)
    sp.set('from', p.from)
    sp.set('to', p.to)
    sp.set('format', p.format)
    return `http://api/affidavit/export?${sp.toString()}`
  })
})

describe('UnderwritingScreen access', () => {
  it('renders all four tabs when the operator has every S24 role', async () => {
    const { findByRole } = renderScreen()
    expect(await findByRole('tab', { name: 'Spots' })).toBeTruthy()
    expect(await findByRole('tab', { name: 'Flights' })).toBeTruthy()
    expect(await findByRole('tab', { name: 'Placements' })).toBeTruthy()
    expect(await findByRole('tab', { name: 'Affidavits' })).toBeTruthy()
  })

  it('shows the screen access banner for a role-less user and does NOT fetch anything', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderScreen()
    expect(
      await findByText(/publish operator, setup admin, or support admin role/i),
    ).toBeTruthy()
    expect(vi.mocked(listUnderwritingSpots)).not.toHaveBeenCalled()
    expect(vi.mocked(listSpotFlights)).not.toHaveBeenCalled()
    expect(vi.mocked(listSpotPlacements)).not.toHaveBeenCalled()
    expect(vi.mocked(getUnderwriterAffidavit)).not.toHaveBeenCalled()
  })

  it('support_admin only — sees Affidavits content, blocks Spots/Flights/Placements with banner', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    const { findByRole, findAllByText, findByText } = renderScreen()
    // Initial tab is Affidavits — affidavit query is gated on filters so it
    // shouldn't fire yet; the underwriter input is empty.
    const affTab = await findByRole('tab', { name: 'Affidavits' })
    expect(affTab.getAttribute('aria-selected')).toBe('true')
    expect(vi.mocked(getUnderwriterAffidavit)).not.toHaveBeenCalled()

    // Spots / Flights / Placements management queries must NOT have fired.
    expect(vi.mocked(listUnderwritingSpots)).not.toHaveBeenCalled()
    expect(vi.mocked(listSpotFlights)).not.toHaveBeenCalled()
    expect(vi.mocked(listSpotPlacements)).not.toHaveBeenCalled()

    // Click into Spots → the manage-denied banner is shown.
    fireEvent.click(await findByRole('tab', { name: 'Spots' }))
    const banners = await findAllByText(/publish operator or setup admin role/i)
    expect(banners.length).toBeGreaterThan(0)
    expect(vi.mocked(listUnderwritingSpots)).not.toHaveBeenCalled()

    // Click into Flights → same banner.
    fireEvent.click(await findByRole('tab', { name: 'Flights' }))
    expect(await findByText(/publish operator or setup admin role/i)).toBeTruthy()
    expect(vi.mocked(listSpotFlights)).not.toHaveBeenCalled()

    // Click into Placements → same banner.
    fireEvent.click(await findByRole('tab', { name: 'Placements' }))
    expect(await findByText(/publish operator or setup admin role/i)).toBeTruthy()
    expect(vi.mocked(listSpotPlacements)).not.toHaveBeenCalled()
  })

  it('publish_operator only — lands on Spots from the first paint (UX-1 initial-tab race)', async () => {
    // UX-1 regression: previously `useState(canManage ? "spots" : "affidavits")`
    // ran at the outer mount BEFORE identity loaded, so `canManage` was false
    // and a manage-only operator was stuck on the access-denied Affidavits
    // banner. The fix splits the screen so the body's state initialiser only
    // runs AFTER identity resolves. Assert here that the Spots tab is the
    // selected one once the screen has rendered — no `fireEvent.click` warmup
    // is needed.
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByRole, findByText } = renderScreen()
    const spotsTab = await findByRole('tab', { name: 'Spots' })
    expect(spotsTab.getAttribute('aria-selected')).toBe('true')
    const affTab = await findByRole('tab', { name: 'Affidavits' })
    expect(affTab.getAttribute('aria-selected')).toBe('false')
    // Spot list fires for the management user.
    await waitFor(() => expect(vi.mocked(listUnderwritingSpots)).toHaveBeenCalled())

    fireEvent.click(affTab)
    expect(await findByText(/affidavits require the support admin role/i)).toBeTruthy()
    expect(vi.mocked(getUnderwriterAffidavit)).not.toHaveBeenCalled()
  })
})

describe('UnderwritingScreen — Spot tab', () => {
  it('renders the verbatim FCC 47 CFR 73.503 reminder under the attestation checkbox', async () => {
    const { findByLabelText, findByText } = renderScreen()
    // No tab-click warmup — the operator with all roles lands on Spots from
    // frame 1 after the UX-1 initial-tab race fix.
    const cb = await findByLabelText(/fcc 47 cfr 73\.503 attestation/i)
    expect(cb).toBeTruthy()
    // The reminder text appears verbatim (we assert two distinctive fragments).
    expect(
      await findByText(/Per 47 CFR 73\.503, underwriting acknowledgments may identify the sponsor/i),
    ).toBeTruthy()
    expect(
      await findByText(/Content is not auto-checked — your attestation is the editorial gate\./i),
    ).toBeTruthy()
  })

  it('submits the right payload on Create spot', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    // UX-1 fix: the screen lands on Spots directly for an all-roles operator.
    // No tab-click warmup is needed.
    fireEvent.change(await findByLabelText('Spot ID'), { target: { value: 'new-spot' } })
    fireEvent.change(await findByLabelText('Underwriter'), { target: { value: 'Acme Co-op' } })
    fireEvent.change(await findByLabelText('Asset ID'), {
      target: { value: 'asset-acme-ack' },
    })
    fireEvent.click(await findByLabelText(/fcc 47 cfr 73\.503 attestation/i))
    fireEvent.change(await findByLabelText('Review notes'), {
      target: { value: 'SC 2026-06-18' },
    })
    await act(async () => {
      fireEvent.click(await findByRole('button', { name: 'Create spot' }))
    })
    await waitFor(() => expect(vi.mocked(createUnderwritingSpot)).toHaveBeenCalledTimes(1))
    expect(vi.mocked(createUnderwritingSpot)).toHaveBeenCalledWith({
      spot_id: 'new-spot',
      station_id: 'civiccast-station',
      underwriter: 'Acme Co-op',
      asset_id: 'asset-acme-ack',
      fcc_compliant_ack: true,
      review_notes: 'SC 2026-06-18',
    })
  })

  it('Delete is a two-step (arm → confirm) with the cascade warning copy', async () => {
    const { findByRole, findByText } = renderScreen()
    // UX-1 fix: the screen lands on Spots directly; no tab-click warmup needed.
    // Wait for the spot row to render.
    await findByRole('button', { name: /^Delete acme-15s$/i })
    // Step 1 — arm. Delete button visible, but Confirm not, and the cascade
    // warning is not yet showing.
    fireEvent.click(await findByRole('button', { name: /^Delete acme-15s$/i }))
    expect(await findByRole('button', { name: /^Confirm delete acme-15s$/i })).toBeTruthy()
    expect(
      await findByText(
        /Confirming will also delete every flight \+ placement that referenced this spot\./i,
      ),
    ).toBeTruthy()
    // Step 2 — confirm. Mutation fires.
    await act(async () => {
      fireEvent.click(await findByRole('button', { name: /^Confirm delete acme-15s$/i }))
    })
    await waitFor(() =>
      expect(vi.mocked(deleteUnderwritingSpot)).toHaveBeenCalledWith('acme-15s'),
    )
  })
})

describe('UnderwritingScreen — Affidavits tab', () => {
  it('builds the right download URL via affidavitExportUrl for CSV/XML/PDF', async () => {
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Affidavits' }))
    fireEvent.change(await findByLabelText('Underwriter'), {
      target: { value: 'Acme Co-op' },
    })
    // UX-5: affidavit filter aria-labels were "Period start"/"Period end" —
    // synced to the visible labels "From date"/"Through date".
    fireEvent.change(await findByLabelText('From date'), {
      target: { value: '2026-07-01' },
    })
    fireEvent.change(await findByLabelText('Through date'), {
      target: { value: '2026-07-31' },
    })
    const csv = (await findByRole('link', {
      name: 'Download affidavit CSV',
    })) as HTMLAnchorElement
    const xml = (await findByRole('link', {
      name: 'Download affidavit XML',
    })) as HTMLAnchorElement
    const pdf = (await findByRole('link', {
      name: 'Download affidavit PDF',
    })) as HTMLAnchorElement
    expect(csv.href).toContain('underwriter=Acme+Co-op')
    expect(csv.href).toContain('from=2026-07-01')
    expect(csv.href).toContain('to=2026-07-31')
    expect(csv.href).toContain('format=csv')
    expect(xml.href).toContain('format=xml')
    expect(pdf.href).toContain('format=pdf')
    // The builder helper must have been called with the right shape.
    expect(vi.mocked(affidavitExportUrl)).toHaveBeenCalledWith({
      underwriter: 'Acme Co-op',
      from: '2026-07-01',
      to: '2026-07-31',
      format: 'csv',
    })
  })

  it('UX-2: zero-airing empty state enumerates the three causes (misspelling, no flights, no airings)', async () => {
    vi.mocked(getUnderwriterAffidavit).mockResolvedValue(
      affidavit({ aired: [], total_airings: 0, total_seconds: 0 }),
    )
    const { findByRole, findByLabelText, findByText } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Affidavits' }))
    fireEvent.change(await findByLabelText('Underwriter'), {
      target: { value: 'Acme Co-op' },
    })
    fireEvent.change(await findByLabelText('From date'), {
      target: { value: '2026-07-01' },
    })
    fireEvent.change(await findByLabelText('Through date'), {
      target: { value: '2026-07-31' },
    })
    expect(
      await findByText(/No airings recorded for/i),
    ).toBeTruthy()
    expect(
      await findByText(/underwriter name does not match a spot exactly/i),
    ).toBeTruthy()
    expect(
      await findByText(/spots but no flights, or no flights overlapping this period/i),
    ).toBeTruthy()
    expect(
      await findByText(/Flights exist but no spots have aired yet in this window/i),
    ).toBeTruthy()
  })

  it('UX-3: affidavit From/Through date inputs get aria-describedby + aria-invalid when the range is invalid', async () => {
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Affidavits' }))
    // Invert the range so From > Through. The default range is the current
    // month — set Through to before From explicitly.
    fireEvent.change(await findByLabelText('From date'), {
      target: { value: '2026-07-31' },
    })
    fireEvent.change(await findByLabelText('Through date'), {
      target: { value: '2026-07-01' },
    })
    const fromInput = (await findByLabelText('From date')) as HTMLInputElement
    const throughInput = (await findByLabelText('Through date')) as HTMLInputElement
    expect(fromInput.getAttribute('aria-invalid')).toBe('true')
    expect(throughInput.getAttribute('aria-invalid')).toBe('true')
    const fromDescribedBy = fromInput.getAttribute('aria-describedby')
    const throughDescribedBy = throughInput.getAttribute('aria-describedby')
    expect(fromDescribedBy).toBeTruthy()
    expect(throughDescribedBy).toBe(fromDescribedBy)
    // The id pointed to by aria-describedby must resolve to the inline
    // range-warning copy.
    const msg = document.getElementById(fromDescribedBy!)
    expect(msg?.textContent ?? '').toMatch(/From date that is on or before the Through date/i)
  })

  it('UX-4: disabled download links are removed from the tab order and reject clicks', async () => {
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Affidavits' }))
    // Underwriter is empty → links are disabled.
    const csv = (await findByRole('link', {
      name: 'Download affidavit CSV',
    })) as HTMLAnchorElement
    const xml = (await findByRole('link', {
      name: 'Download affidavit XML',
    })) as HTMLAnchorElement
    const pdf = (await findByRole('link', {
      name: 'Download affidavit PDF',
    })) as HTMLAnchorElement
    for (const link of [csv, xml, pdf]) {
      expect(link.getAttribute('aria-disabled')).toBe('true')
      expect(link.getAttribute('tabindex')).toBe('-1')
    }
    // Clicking a disabled link must NOT trigger default navigation.
    const evt = new MouseEvent('click', { bubbles: true, cancelable: true })
    csv.dispatchEvent(evt)
    expect(evt.defaultPrevented).toBe(true)
  })
})
