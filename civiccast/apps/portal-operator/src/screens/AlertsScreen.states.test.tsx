// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as api from '../api/client'
import { AlertsScreen } from './AlertsScreen'

const clients: QueryClient[] = []
beforeEach(() => {
  vi.spyOn(api, 'getStaffIdentity').mockResolvedValue({
    operator_id: 'example', operator_display_name: 'Example operator', roles: ['setup_admin'],
  })
  vi.spyOn(api, 'listAlertEvents').mockResolvedValue([])
  vi.spyOn(api, 'listAlertRules').mockResolvedValue([])
  vi.spyOn(api, 'listAlertChannels').mockResolvedValue([])
})
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.restoreAllMocks()
})

function screen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return { client, ...render(<QueryClientProvider client={client}><AlertsScreen /></QueryClientProvider>) }
}

describe('Alerts list evidence states', () => {
  it('does not show successful empty results after failed reads', async () => {
    vi.mocked(api.listAlertEvents).mockRejectedValue(new Error('Alert request unavailable'))
    vi.mocked(api.listAlertChannels).mockRejectedValue(new Error('Destination request unavailable'))
    const view = screen()
    await view.findByText('Alert request unavailable')
    await view.findByText('Destination request unavailable')
    expect(view.queryByText(/No active alerts/)).toBeNull()
    expect(view.queryByText(/No alert destinations yet/)).toBeNull()
    expect(view.queryByText(/monitors is healthy/)).toBeNull()
  })

  it('offers an explicit read-only retry and recovers the alerts list', async () => {
    vi.mocked(api.listAlertEvents).mockRejectedValueOnce(new Error('Temporary alert failure'))
    const view = screen()
    await view.findByText('Temporary alert failure')
    fireEvent.click(view.getByRole('button', { name: 'Retry alerts' }))
    expect(await view.findByText(/No active alerts were returned/)).toBeTruthy()
    expect(view.queryByText('Temporary alert failure')).toBeNull()
    expect(api.listAlertEvents).toHaveBeenCalledTimes(2)
  })

  it('does not present an empty list as proof of healthy monitoring', async () => {
    const view = screen()
    expect(await view.findByText(/No active alerts were returned/)).toBeTruthy()
    expect(view.getByText(/This does not verify station health/)).toBeTruthy()
    expect(view.queryByText(/monitors is healthy/)).toBeNull()
    expect(await view.findByText(/No alert destinations yet/)).toBeTruthy()
  })

  it('shows loading without empty or healthy claims', () => {
    vi.mocked(api.listAlertEvents).mockReturnValue(new Promise(() => {}))
    const view = screen()
    expect(view.getByText('Loading alerts...')).toBeTruthy()
    expect(view.queryByText(/No active alerts/)).toBeNull()
    expect(view.queryByText(/monitors is healthy/)).toBeNull()
  })

  it('withdraws the empty claim if a later refresh fails', async () => {
    const view = screen()
    await view.findByText(/No active alerts/)
    vi.mocked(api.listAlertEvents).mockRejectedValue(new Error('Refresh unavailable'))
    await view.client.invalidateQueries({ queryKey: ['alert-events'] })
    await view.findByText('Refresh unavailable')
    await waitFor(() => expect(view.queryByText(/No active alerts/)).toBeNull())
  })

  it('keeps the successful resolved-history empty state', async () => {
    const view = screen()
    await view.findByText(/No active alerts/)
    fireEvent.click(view.getByRole('button', { name: 'Resolved' }))
    expect(await view.findByText('No resolved alerts in the recent history.')).toBeTruthy()
    expect(api.listAlertEvents).toHaveBeenLastCalledWith({ state: 'resolved', limit: 200 })
  })
})
