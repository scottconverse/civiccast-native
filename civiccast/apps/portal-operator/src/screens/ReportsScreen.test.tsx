// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  AsRunReport,
  ChannelProfile,
  HoursByCategoryReport,
  ShowsReport,
  StaffIdentityResponse,
} from '../types/api.generated'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
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
  getStaffIdentity: vi.fn(),
  getAsRunReport: vi.fn(),
  getShowsReport: vi.fn(),
  getHoursByCategoryReport: vi.fn(),
  listChannels: vi.fn(),
  downloadReportsExport: vi.fn(),
}))

import {
  downloadReportsExport,
  getAsRunReport,
  getHoursByCategoryReport,
  getShowsReport,
  getStaffIdentity,
  listChannels,
} from '../api/client'
import { ReportsScreen } from './ReportsScreen'

function channel(channel_id: string, slug = channel_id): ChannelProfile {
  return {
    channel_id,
    slug,
    kind: 'public',
    branding: { display_name: slug } as ChannelProfile['branding'],
    fallback_behavior: 'slate',
  } as ChannelProfile
}

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'sam', operator_display_name: 'Sam', roles } as StaffIdentityResponse
}

function shows(rows: ShowsReport['rows'] = []): ShowsReport {
  return {
    station_id: 'civiccast-station',
    from_ts: '2026-06-01T00:00:00Z',
    to_ts: '2026-06-02T00:00:00Z',
    rows,
  }
}

function asRun(rows: AsRunReport['rows'] = []): AsRunReport {
  return {
    station_id: 'civiccast-station',
    from_ts: '2026-06-01T00:00:00Z',
    to_ts: '2026-06-02T00:00:00Z',
    rows,
  }
}

function hours(
  overrides: Partial<HoursByCategoryReport> = {},
): HoursByCategoryReport {
  return {
    station_id: 'civiccast-station',
    from_ts: '2026-06-01T00:00:00Z',
    to_ts: '2026-06-02T00:00:00Z',
    field_key: 'category',
    field_not_found: false,
    rows: [],
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ReportsScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal(
    'URL',
    Object.assign(URL, {
      createObjectURL: vi.fn(() => 'blob:report-export'),
      revokeObjectURL: vi.fn(),
    }),
  )
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
  vi.mocked(getShowsReport).mockResolvedValue(shows())
  vi.mocked(getAsRunReport).mockResolvedValue(asRun())
  vi.mocked(getHoursByCategoryReport).mockResolvedValue(hours())
  vi.mocked(listChannels).mockResolvedValue([channel('pub-1'), channel('gov-1')])
  vi.mocked(downloadReportsExport).mockResolvedValue(new Blob(['ok'], { type: 'text/csv' }))
})

describe('ReportsScreen access', () => {
  it('shows an access banner for a non-support_admin role and does NOT fetch reports', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/require the support admin role/i)).toBeTruthy()
    // The role gate must prevent any of the report queries from firing.
    expect(vi.mocked(getShowsReport)).not.toHaveBeenCalled()
    expect(vi.mocked(getAsRunReport)).not.toHaveBeenCalled()
    expect(vi.mocked(getHoursByCategoryReport)).not.toHaveBeenCalled()
  })

  it('renders the three tabs for a support admin', async () => {
    const { findByRole } = renderScreen()
    expect(await findByRole('tab', { name: 'Shows' })).toBeTruthy()
    expect(await findByRole('tab', { name: 'As-Run' })).toBeTruthy()
    expect(await findByRole('tab', { name: 'Hours by Category' })).toBeTruthy()
  })
})

describe('ReportsScreen filters + download links', () => {
  it('exposes the date range controls (UTC-labeled) and defaults to a single-day window', async () => {
    const { findByLabelText } = renderScreen()
    const from = (await findByLabelText('From date (UTC)')) as HTMLInputElement
    const to = (await findByLabelText('Through date (UTC)')) as HTMLInputElement
    expect(from.value.length).toBe(10)
    expect(to.value.length).toBe(10)
    expect(from.value < to.value).toBe(true)
    // UX-2: default range is a SINGLE-day window (today → tomorrow), not a month back.
    const fromDate = new Date(`${from.value}T00:00:00Z`).getTime()
    const toDate = new Date(`${to.value}T00:00:00Z`).getTime()
    expect(toDate - fromDate).toBe(86_400_000)
  })

  it('downloads CSV through the authenticated export helper', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText('From date (UTC)'), { target: { value: '2026-06-01' } })
    fireEvent.change(await findByLabelText('Through date (UTC)'), {
      target: { value: '2026-06-08' },
    })
    fireEvent.change(await findByLabelText('Channel'), { target: { value: 'pub-1' } })
    fireEvent.click(await findByRole('button', { name: /download shows csv/i }))
    await waitFor(() =>
      expect(vi.mocked(downloadReportsExport)).toHaveBeenCalledWith({
        type: 'shows',
        format: 'csv',
        from: '2026-06-01T00:00:00Z',
        to: '2026-06-08T00:00:00Z',
        channel: 'pub-1',
        field: undefined,
      }),
    )
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:report-export')
  })

  it('shows an in-page warning when an export download fails', async () => {
    vi.mocked(downloadReportsExport).mockRejectedValue(new Error('download failed'))
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /download shows csv/i }))
    expect(await findByText(/download failed/i)).toBeTruthy()
  })

  it('uses a SELECT for the channel filter and pre-populates it from listChannels', async () => {
    const { findByLabelText, findByText } = renderScreen()
    const ch = (await findByLabelText('Channel')) as HTMLSelectElement
    expect(ch.tagName).toBe('SELECT')
    // First option is the "all channels" sentinel.
    expect(ch.options[0].value).toBe('')
    // Wait for the async listChannels query to populate options.
    await findByText(/pub-1 \(pub-1\)/i)
    const values = Array.from(ch.options).map((o) => o.value)
    expect(values).toContain('pub-1')
    expect(values).toContain('gov-1')
  })
})

describe('ReportsScreen empty + deploy-day states', () => {
  it('shows a deploy-day info banner when both Shows + As-Run come back empty (no field_not_found)', async () => {
    const { findByText } = renderScreen()
    expect(
      await findByText(/No content has aired yet on this station/i),
    ).toBeTruthy()
  })

  it('uses the new deploy-day-friendly empty-state copy on the Shows tab', async () => {
    const { findByText } = renderScreen()
    expect(await findByText(/No air times in the selected range/i)).toBeTruthy()
  })
})

describe('ReportsScreen tabs ARIA wiring', () => {
  it('renders each tab linked to a tabpanel via aria-controls', async () => {
    const { findByRole, getAllByRole } = renderScreen()
    const showsTab = (await findByRole('tab', { name: 'Shows' })) as HTMLButtonElement
    expect(showsTab.getAttribute('aria-controls')).toBe('panel-shows')
    // tabpanels exist for every tab (each section has role=tabpanel).
    const panels = getAllByRole('tabpanel', { hidden: true })
    const panelIds = panels.map((p) => p.id).sort()
    expect(panelIds).toEqual(['panel-as-run', 'panel-hours', 'panel-shows'])
  })

  it('supports ArrowRight to move to the next tab and update aria-selected', async () => {
    const { findByRole } = renderScreen()
    const showsTab = (await findByRole('tab', { name: 'Shows' })) as HTMLButtonElement
    showsTab.focus()
    fireEvent.keyDown(showsTab, { key: 'ArrowRight' })
    const asRunTab = (await findByRole('tab', { name: 'As-Run' })) as HTMLButtonElement
    await waitFor(() => expect(asRunTab.getAttribute('aria-selected')).toBe('true'))
  })
})

describe('ReportsScreen hours-by-category', () => {
  it('shows the field_not_found banner when the server returns it', async () => {
    vi.mocked(getHoursByCategoryReport).mockResolvedValue(
      hours({ field_key: 'category', field_not_found: true }),
    )
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Hours by Category' }))
    expect(await findByText(/No custom field named "category"/i)).toBeTruthy()
  })

  it('passes the field key to the API query', async () => {
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('tab', { name: 'Hours by Category' }))
    const fld = (await findByLabelText('Custom field key')) as HTMLInputElement
    fireEvent.change(fld, { target: { value: 'genre' } })
    await waitFor(() =>
      expect(vi.mocked(getHoursByCategoryReport)).toHaveBeenCalledWith(
        expect.objectContaining({ field: 'genre' }),
      ),
    )
  })
})
