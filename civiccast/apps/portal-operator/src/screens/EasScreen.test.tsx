// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { EasCapAlert, EasCapSource, StaffIdentityResponse } from '../types/api.generated'

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
  listChannelProfiles: vi.fn(),
  listEasSources: vi.fn(),
  listEasAlerts: vi.fn(),
  listEasDecisions: vi.fn(),
  displayEasAlert: vi.fn(),
  clearEasDecision: vi.fn(),
}))

import {
  displayEasAlert,
  getStaffIdentity,
  listChannelProfiles,
  listEasAlerts,
  listEasDecisions,
  listEasSources,
} from '../api/client'
import { EasScreen } from './EasScreen'

beforeEach(() => {
  vi.mocked(listChannelProfiles).mockResolvedValue([])
  vi.mocked(listEasSources).mockResolvedValue([])
  vi.mocked(listEasAlerts).mockResolvedValue([])
  vi.mocked(listEasDecisions).mockResolvedValue([])
})

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

const SOURCE: EasCapSource = {
  source_id: 'src_nws',
  label: 'NWS',
  kind: 'nws-cap',
  severity_floor: 'severe',
  enabled: true,
}

const ALERT: EasCapAlert = {
  alert_id: 'a1',
  source_id: 'src_nws',
  sender: 'snd',
  identifier: 'a1',
  sent: '2026-01-01T12:00:00Z',
  msg_type: 'alert',
  status: 'active',
  event: 'Tornado Warning',
  severity: 'extreme',
  headline: 'Tornado Warning issued',
  areas: ['MNZ001'],
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EasScreen />
    </QueryClientProvider>,
  )
}

describe('EasScreen', () => {
  it('shows the not-an-EAS-device posture even to a non-privileged operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    const { findByText, findAllByText } = renderScreen()
    expect((await findAllByText(/not an EAS device/i)).length).toBeGreaterThan(0)
    expect(await findByText(/requires the setup admin, support admin, or meeting operator/i)).toBeTruthy()
  })

  it('lists sources and active alerts for a support admin (read-only)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(listEasSources).mockResolvedValue([SOURCE])
    vi.mocked(listEasAlerts).mockResolvedValue([ALERT])
    vi.mocked(listEasDecisions).mockResolvedValue([])
    const { findByText, queryByText } = renderScreen()
    expect(await findByText('NWS')).toBeTruthy()
    expect(await findByText('Tornado Warning')).toBeTruthy()
    expect(await findByText(/read-only/i)).toBeTruthy()
    // a support admin cannot display — no crawl button
    expect(queryByText(/Show crawl/i)).toBeNull()
  })

  it('keeps the forced-slate confirmation per-alert (arming one does not arm another)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(listEasAlerts).mockResolvedValue([
      ALERT,
      { ...ALERT, alert_id: 'a2', identifier: 'a2', event: 'Flash Flood Warning', severity: 'severe' },
    ])
    vi.mocked(displayEasAlert).mockResolvedValue({
      decision_id: 'd1', alert_id: 'a1', channel_id: 'gov', mode: 'forced_slate',
      state: 'displayed', decided_by: 'dana', eas_claim: 'not_eas',
    })
    const { findAllByText, getAllByRole } = renderScreen()
    const slateButtons = (await findAllByText(/Forced slate/i)) as HTMLButtonElement[]
    expect(slateButtons).toHaveLength(2)
    expect(slateButtons[0].disabled).toBe(true)
    expect(slateButtons[1].disabled).toBe(true)
    // arm the FIRST alert's confirm checkbox
    const checkboxes = getAllByRole('checkbox') as HTMLInputElement[]
    fireEvent.click(checkboxes[0])
    expect(slateButtons[0].disabled).toBe(false)
    expect(slateButtons[1].disabled).toBe(true) // the other alert's takeover is NOT armed
    // firing the first resets its confirmation (single-use)
    fireEvent.click(slateButtons[0])
    await waitFor(() =>
      expect(vi.mocked(displayEasAlert)).toHaveBeenCalledWith('a1', {
        channel_id: 'gov',
        mode: 'forced_slate',
        operator_confirmed: true,
      }),
    )
    expect(slateButtons[0].disabled).toBe(true) // re-disabled after firing
  })

  it('lets a meeting operator display an alert as a crawl', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(listEasSources).mockResolvedValue([])
    vi.mocked(listEasAlerts).mockResolvedValue([ALERT])
    vi.mocked(listEasDecisions).mockResolvedValue([])
    vi.mocked(displayEasAlert).mockResolvedValue({
      decision_id: 'd1',
      alert_id: 'a1',
      channel_id: 'gov',
      mode: 'crawl',
      state: 'displayed',
      decided_by: 'dana',
      eas_claim: 'not_eas',
    })
    const { findByText } = renderScreen()
    const button = await findByText(/Show crawl on gov/i)
    fireEvent.click(button)
    await waitFor(() =>
      expect(vi.mocked(displayEasAlert)).toHaveBeenCalledWith('a1', {
        channel_id: 'gov',
        mode: 'crawl',
        operator_confirmed: false,
      }),
    )
  })
})
