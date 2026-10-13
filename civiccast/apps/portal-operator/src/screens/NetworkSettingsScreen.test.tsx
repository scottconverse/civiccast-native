import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { StaffIdentityResponse } from '../types/api.generated'
import type { NetworkSettings, NetworkSettingsResponse } from '../types/network'

afterEach(cleanup)
beforeEach(() => vi.clearAllMocks())

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
  getNetworkSettings: vi.fn(),
  getStaffIdentity: vi.fn(),
  saveNetworkSettings: vi.fn(),
}))

import { getNetworkSettings, getStaffIdentity, saveNetworkSettings } from '../api/client'
import { NetworkSettingsScreen } from './NetworkSettingsScreen'

const loopbackSettings: NetworkSettings = {
  mode: 'loopback',
  public_base_url: null,
  staff_hostname: null,
  staff_allowed_cidrs: [],
  caddy_bind_addresses: [],
  upstream_host: '127.0.0.1',
  upstream_port: 8000,
}

function response(settings: NetworkSettings, caddyfile = '', restart_required = false): NetworkSettingsResponse {
  return { settings, caddyfile, restart_required }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><NetworkSettingsScreen /></QueryClientProvider>)
}

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'operator', operator_display_name: 'Operator', roles } as StaffIdentityResponse
}

describe('NetworkSettingsScreen', () => {
  it('keeps the default loopback state clear and setup-admin only can edit', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getNetworkSettings).mockResolvedValue(response(loopbackSettings))

    renderScreen()

    expect(await screen.findByText(/available on this computer only/i)).toBeTruthy()
    expect(screen.getByLabelText('Access mode').hasAttribute('disabled')).toBe(false)
    expect(screen.queryByLabelText('Generated Caddy configuration')).toBeNull()
  })

  it('saves separated public and restricted staff hosts and shows restart/config guidance', async () => {
    const caddySettings: NetworkSettings = {
      mode: 'caddy',
      public_base_url: 'https://watch.example.gov',
      staff_hostname: 'staff.example.gov',
      staff_allowed_cidrs: ['192.168.50.0/24'],
      caddy_bind_addresses: [],
      upstream_host: '127.0.0.1',
      upstream_port: 8000,
    }
    const generated = 'https://watch.example.gov {\n    respond "Not found" 404\n}\n'
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getNetworkSettings).mockResolvedValue(response(loopbackSettings))
    vi.mocked(saveNetworkSettings).mockResolvedValue(response(caddySettings, generated, true))

    renderScreen()
    await screen.findByText(/available on this computer only/i)
    fireEvent.change(screen.getByLabelText('Access mode'), { target: { value: 'caddy' } })
    fireEvent.change(screen.getByLabelText('Public HTTPS URL'), { target: { value: caddySettings.public_base_url } })
    fireEvent.change(screen.getByLabelText('Staff HTTPS hostname'), { target: { value: caddySettings.staff_hostname } })
    fireEvent.change(screen.getByLabelText('Staff network CIDRs'), { target: { value: '192.168.50.0/24' } })
    const staffSignIn = await screen.findByRole('link', { name: 'Staff sign-in: https://staff.example.gov/operator/#/login' })
    expect(staffSignIn.getAttribute('href')).toBe('https://staff.example.gov/operator/#/login')
    fireEvent.click(screen.getByRole('button', { name: 'Save network settings' }))

    await waitFor(() => expect(vi.mocked(saveNetworkSettings).mock.calls[0]?.[0]).toEqual(caddySettings))
    expect((await screen.findByLabelText('Generated Caddy configuration', { selector: 'textarea' }) as HTMLTextAreaElement).value).toBe(generated)
    expect(screen.getByRole('status').textContent).toMatch(/restart the civiccast service/i)
    expect(screen.getByRole('link', { name: 'Download Caddyfile' })).toBeTruthy()
  })

  it('keeps support-admin access read-only and refuses unrelated roles', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(getNetworkSettings).mockResolvedValue(response(loopbackSettings))

    renderScreen()
    await screen.findByText(/available on this computer only/i)
    expect(screen.getByLabelText('Access mode').hasAttribute('disabled')).toBe(true)
    expect(screen.queryByRole('button', { name: 'Save network settings' })).toBeNull()

    cleanup()
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    renderScreen()
    expect(await screen.findByText(/requires the setup admin or support admin role/i)).toBeTruthy()
    expect(getNetworkSettings).toHaveBeenCalledTimes(1)
  })
})
