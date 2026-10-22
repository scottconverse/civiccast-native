import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { StaffIdentityResponse } from '../types/api.generated'

vi.mock('../api/client', () => ({ getStaffIdentity: vi.fn() }))
vi.mock('../api/federation', () => ({
  listFederationStations: vi.fn(), getFederationCatalog: vi.fn(),
  getFederationChannels: vi.fn(), queueFederationCommand: vi.fn(),
}))
import { getStaffIdentity } from '../api/client'
import { getFederationCatalog, getFederationChannels, listFederationStations, queueFederationCommand } from '../api/federation'
import { StationFederationScreen } from './StationFederationScreen'

afterEach(() => { cleanup(); vi.resetAllMocks() })
function renderScreen(role = 'meeting_operator') {
  vi.mocked(getStaffIdentity).mockResolvedValue({ roles: [role] } as StaffIdentityResponse)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={client}><StationFederationScreen /></QueryClientProvider></MemoryRouter>)
}
function configurePeer() {
  vi.mocked(listFederationStations).mockResolvedValue([{ station_id: 'north', label: 'North station', public_origin: 'https://north.example', channel_ids: ['public'], control_configured: true }])
  vi.mocked(getFederationCatalog).mockResolvedValue({ station_id: 'north', items: [{ asset_id: 'meeting', title: 'Council meeting', duration_seconds: 3600, published_at: '2026-10-16T12:00:00Z', portal_url: 'https://north.example/#/watch/meeting' }], truncated: false })
  vi.mocked(getFederationChannels).mockResolvedValue({ station_id: 'north', channels: [{ channel_id: 'public', enabled: true, state: 'running', current_source_label: 'Town hall', last_health_at: null }] })
}
describe('StationFederationScreen', () => {
  it('does not load stations for staff without a permitted role', async () => {
    renderScreen('viewer')
    expect(await screen.findByText(/Your staff role does not allow/)).toBeTruthy()
    expect(listFederationStations).not.toHaveBeenCalled()
  })
  it('explains an empty configured station list', async () => {
    vi.mocked(listFederationStations).mockResolvedValue([])
    renderScreen()
    expect(await screen.findByText(/No other stations are configured/)).toBeTruthy()
    expect(getFederationCatalog).not.toHaveBeenCalled()
  })
  it('opens published programs and confirms a stop before showing only a queued acknowledgement', async () => {
    configurePeer()
    vi.mocked(queueFederationCommand).mockResolvedValue({ station_id: 'north', channel_id: 'public', action: 'stop', command_id: 'cmd-1', queued: true, message: 'Queued on remote station; refresh status to confirm execution.' })
    renderScreen()
    const link = await screen.findByRole('link', { name: /Watch Council meeting/ })
    expect(link.getAttribute('href')).toBe('https://north.example/#/watch/meeting')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(await screen.findByText('running')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Stop public' }))
    const dialog = screen.getByRole('alertdialog')
    expect(queueFederationCommand).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm stop' }))
    await waitFor(() => expect(queueFederationCommand).toHaveBeenCalledWith('north', 'public', 'stop'))
    expect((await screen.findByRole('status')).textContent).toMatch(/queued.*Refresh status to confirm execution/i)
    expect(screen.getByText('running')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh channel status' }))
    await waitFor(() => expect(getFederationChannels).toHaveBeenCalledTimes(2))
  })
  it('allows catalog readers to see status without command controls and offers retry after a catalog failure', async () => {
    configurePeer()
    vi.mocked(getFederationCatalog).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValue({ station_id: 'north', items: [], truncated: false })
    renderScreen('publish_operator')
    expect(await screen.findByText('Could not load published programs.')).toBeTruthy()
    expect(await screen.findByText('running')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Stop public' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry published programs' }))
    expect(await screen.findByText('No published programs are available.')).toBeTruthy()
  })
})
