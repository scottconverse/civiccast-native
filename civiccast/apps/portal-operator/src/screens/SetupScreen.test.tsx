import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { BackupSetupPanel, R2ConciergeCard, SetupScreen } from './SetupScreen'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function renderSetupScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SetupScreen />
    </QueryClientProvider>,
  )
}

function inputById(id: string) {
  const input = document.querySelector<HTMLInputElement>(`#${id}`)
  if (!input) throw new Error(`missing input #${id}`)
  return input
}

const profile = {
  station_name: 'CivicCast Test Station',
  admin_display_name: 'Test Admin',
  admin_username: 'testadmin',
  default_channel_id: 'gov-ch12',
  public_base_url: 'http://127.0.0.1:8000/',
  station_timezone: 'America/Denver',
  storage_locations: {
    media_library: 'C:\\Users\\tester\\AppData\\Local\\CivicCast\\media',
    recordings: 'C:\\Users\\tester\\AppData\\Local\\CivicCast\\recordings',
    backups: 'C:\\Users\\tester\\AppData\\Local\\CivicCast\\backups',
  },
  channel_count: 3,
  channel_profiles: [
    {
      channel_id: 'gov-ch12',
      display_name: 'Government Channel 12',
      purpose: 'Public meetings, civic boards, and official notices.',
    },
    {
      channel_id: 'edu-ch13',
      display_name: 'Education Channel 13',
      purpose: 'School board, campus, student, and athletics programming.',
    },
    {
      channel_id: 'community-ch14',
      display_name: 'Community Channel 14',
      purpose: 'Community producers, events, bulletin boards, and local culture.',
    },
  ],
  sample_content_enabled: true,
  initial_schedule_enabled: true,
  default_roles: ['setup_admin', 'publish_operator', 'support_admin', 'viewer'],
  operation_mode: 'test',
  dashboard_ready_state: 'not_ready',
  recovery_kit_id: 'rk_test',
  recovery_kit_generated_at: '2026-06-28T00:00:00Z',
}

function renderR2ConciergeCard(canManageProviders = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <R2ConciergeCard canManageProviders={canManageProviders} />
    </QueryClientProvider>,
  )
}

function renderBackupSetupPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BackupSetupPanel />
    </QueryClientProvider>,
  )
}

describe('BackupSetupPanel', () => {
  it('prepopulates the configured default so verification needs no path retyping', async () => {
    const destination = '/var/lib/civiccast/home/.local/share/civiccast/backups'
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/staff/installer/backup')
      if ((init?.method ?? 'GET') === 'POST') {
        expect(JSON.parse(String(init?.body))).toEqual({ destination })
      }
      return jsonResponse({
        generated_at: '2026-07-15T00:00:00Z',
        status: 'ready',
        destination,
        last_probe_at: '2026-07-15T00:00:00Z',
        last_backup_at: null,
        message: 'Backup folder is ready.',
        next_step: 'Keep it connected.',
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderBackupSetupPanel()

    await waitFor(() => expect(inputById('backup-destination').value).toBe(destination))
    const verify = screen.getByRole('button', { name: 'Verify backup' }) as HTMLButtonElement
    expect(verify.disabled).toBe(false)
    fireEvent.click(verify)

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/staff/installer/backup',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })
})

describe('R2ConciergeCard', () => {
  it('provisions R2 from one pasted token and shows the resulting media URL', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/staff/installer/cdn-concierge/r2' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        expect(body.token).toBe('cf-token-123')
        return jsonResponse({
          status: 'ok',
          message: 'R2 storage is ready.',
          bucket: 'civiccast-media',
          public_base_url: 'https://pub-abc123.r2.dev',
        })
      }
      return jsonResponse({ detail: `Unhandled ${String(init?.method ?? 'GET')} ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderR2ConciergeCard()

    fireEvent.change(inputById('r2-concierge-token'), { target: { value: 'cf-token-123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Provision for me' }))

    expect(await screen.findByText(/Media will be served from https:\/\/pub-abc123\.r2\.dev/)).toBeTruthy()
    // the pasted token is cleared from the field after a successful provision.
    await waitFor(() => expect(inputById('r2-concierge-token').value).toBe(''))
  })

  it('shows the guided r2_not_enabled state with its dashboard deep link and a Retry button', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        status: 'failed',
        message: 'R2 is not enabled on this Cloudflare account yet.',
        error_code: 'r2_not_enabled',
        deep_link: 'https://dash.cloudflare.com/?to=/:account/r2',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderR2ConciergeCard()

    fireEvent.change(inputById('r2-concierge-token'), { target: { value: 'cf-token-123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Provision for me' }))

    expect(await screen.findByText('R2 is not enabled on this Cloudflare account yet.')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'Enable R2 on Cloudflare' })
    expect(link.getAttribute('href')).toBe('https://dash.cloudflare.com/?to=/:account/r2')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })

  it('disables the provision button when the operator cannot manage providers', () => {
    renderR2ConciergeCard(false)
    expect(inputById('r2-concierge-token').disabled).toBe(true)
    const button = screen.getByRole('button', { name: 'Provision for me' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })
})

describe('SetupScreen first-admin form validation', () => {
  function stubStorageReadyFetch() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/setup/station-state') {
        return jsonResponse({
          status: 'not_started',
          setup_complete: false,
          profile: null,
          recovery_kit_created: false,
          recovery_kit_id: null,
          recovery_kit_acknowledged: false,
          operator_console_url: null,
          next_step: 'Create the first admin.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({
          status: 'ready',
          database_url: 'sqlite:///tmp/civiccast.db',
          database_path: '/tmp/civiccast.db',
          upload_dir: '/tmp/uploads',
          storage_dir: '/tmp',
          migrations_applied: true,
          configured_at: '2026-06-28T00:00:00Z',
          operator_message: 'Storage ready',
          next_step: 'Create the first admin.',
        })
      }
      if (url === '/api/staff/auth/me') {
        return jsonResponse({ detail: 'no staff session' }, 401)
      }
      return jsonResponse({ detail: `Unhandled GET ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('blocks submit and shows a mismatch message when the confirm field disagrees', async () => {
    stubStorageReadyFetch()
    renderSetupScreen()
    await screen.findByText('Station name')

    fireEvent.change(inputById('station_name'), { target: { value: 'Test Station' } })
    fireEvent.change(inputById('admin_display_name'), { target: { value: 'Test Admin' } })
    fireEvent.change(inputById('admin_username'), { target: { value: 'testadmin' } })
    fireEvent.change(inputById('admin_password'), { target: { value: 'correct horse battery staple' } })
    fireEvent.change(inputById('confirm_password'), { target: { value: 'different password entirely' } })
    fireEvent.blur(inputById('confirm_password'))
    fireEvent.change(inputById('recovery_kit_destination'), { target: { value: 'printed and stored offline' } })

    expect(await screen.findByText('Passwords do not match.')).toBeTruthy()
    const submit = screen.getByRole('button', { name: 'Create first admin' }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    fireEvent.change(inputById('confirm_password'), { target: { value: 'correct horse battery staple' } })
    expect(screen.queryByText('Passwords do not match.')).toBeNull()
    expect(submit.disabled).toBe(false)
  })

  it('toggles the admin password field between hidden and revealed', async () => {
    stubStorageReadyFetch()
    renderSetupScreen()
    await screen.findByText('Station name')

    const passwordInput = inputById('admin_password')
    expect(passwordInput.type).toBe('password')

    const revealButtons = screen.getAllByRole('button', { name: 'Show' })
    fireEvent.click(revealButtons[0])
    expect(passwordInput.type).toBe('text')

    fireEvent.click(screen.getByRole('button', { name: 'Hide' }))
    expect(passwordInput.type).toBe('password')
  })

  it('shows inline hints for unmet requirements once a field is touched', async () => {
    stubStorageReadyFetch()
    renderSetupScreen()
    await screen.findByText('Station name')

    fireEvent.blur(inputById('station_name'))
    expect(await screen.findByText('Station name is required.')).toBeTruthy()

    fireEvent.change(inputById('admin_password'), { target: { value: 'short' } })
    fireEvent.blur(inputById('admin_password'))
    expect(await screen.findByText('Needs at least 12 characters (5/12 so far).')).toBeTruthy()
    expect(screen.getByText('Use at least 12 characters (5/12).')).toBeTruthy()

    fireEvent.blur(inputById('recovery_kit_destination'))
    expect(await screen.findByText('Tell us where the recovery kit will be kept.')).toBeTruthy()
  })
})

describe('SetupScreen first-admin recovery kit gate', () => {
  it('leaves the one-time recovery kit panel after acknowledgement succeeds', async () => {
    window.history.replaceState(null, '', '/operator/?nonce=fresh-setup-nonce#/setup')
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:civiccast-recovery-kit'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.spyOn(window, 'print').mockImplementation(() => {})

    let setupComplete = false
    let recoveryKitAcknowledged = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/setup/station-state') {
        return jsonResponse({
          status: setupComplete ? 'complete' : 'not_started',
          setup_complete: setupComplete,
          profile: setupComplete ? profile : null,
          recovery_kit_created: setupComplete,
          recovery_kit_id: setupComplete ? 'rk_test' : null,
          recovery_kit_acknowledged: recoveryKitAcknowledged,
          operator_console_url: 'http://127.0.0.1:8000/operator/?nonce=fresh-setup-nonce',
          next_step: setupComplete ? 'Open System Health.' : 'Create the first admin.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({
          status: 'ready',
          database_url: 'sqlite:///tmp/civiccast.db',
          database_path: '/tmp/civiccast.db',
          upload_dir: '/tmp/uploads',
          storage_dir: '/tmp',
          migrations_applied: true,
          configured_at: '2026-06-28T00:00:00Z',
          operator_message: 'Storage ready',
          next_step: 'Create the first admin.',
        })
      }
      if (url === '/api/staff/auth/me') {
        return jsonResponse({
          operator_id: 'testadmin',
          operator_display_name: 'Test Admin',
          roles: ['setup_admin', 'meeting_operator', 'records_clerk', 'publish_operator', 'support_admin'],
        })
      }
      if (url === '/api/setup/first-admin' && method === 'POST') {
        setupComplete = true
        return jsonResponse({
          status: 'complete',
          profile,
          recovery_kit: {
            kit_id: 'rk_test',
            generated_at: '2026-06-28T00:00:00Z',
            station_name: profile.station_name,
            admin_username: profile.admin_username,
            recovery_codes: ['CC-ONE', 'CC-TWO'],
            instructions: ['Store the kit offline.'],
            excludes: ['staff bearer token values'],
          },
          operator_console_url: 'http://127.0.0.1:8000/operator/?nonce=fresh-setup-nonce',
          operator_console_token: 'ccst_test_operator_console_token',
          next_step: 'Save the recovery kit.',
        })
      }
      if (url === '/api/setup/recovery-kit/acknowledge' && method === 'POST') {
        recoveryKitAcknowledged = true
        return jsonResponse({
          status: 'complete',
          setup_complete: true,
          profile,
          recovery_kit_created: true,
          recovery_kit_id: 'rk_test',
          recovery_kit_acknowledged: true,
          operator_console_url: 'http://127.0.0.1:8000/operator/?nonce=fresh-setup-nonce',
          next_step: 'Open System Health.',
        })
      }
      return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()

    await screen.findByText('Station name')
    fireEvent.change(inputById('station_name'), {
      target: { value: profile.station_name },
    })
    fireEvent.change(inputById('admin_display_name'), {
      target: { value: profile.admin_display_name },
    })
    fireEvent.change(inputById('admin_username'), {
      target: { value: profile.admin_username },
    })
    fireEvent.change(inputById('admin_password'), {
      target: { value: 'correct horse battery staple' },
    })
    fireEvent.change(inputById('confirm_password'), {
      target: { value: 'correct horse battery staple' },
    })
    fireEvent.change(inputById('recovery_kit_destination'), {
      target: { value: 'printed and stored offline' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create first admin' }))
    expect(await screen.findByText('Recovery kit ready')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Save kit' }))
    fireEvent.click(screen.getByRole('checkbox', { name: /I have saved or printed these recovery codes/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue to the console' }))

    await waitFor(() => {
      expect(screen.queryByText('Recovery kit ready')).toBeNull()
      expect(screen.getByText('Setup complete')).toBeTruthy()
    })
    expect(screen.getByText('First-run defaults')).toBeTruthy()
    expect(screen.getByText('America/Denver')).toBeTruthy()
    expect(screen.getByText('Test mode')).toBeTruthy()
    expect(screen.getByText('Not ready')).toBeTruthy()
    expect(screen.getByText('Government Channel 12')).toBeTruthy()
    expect(screen.getByText('Education Channel 13')).toBeTruthy()
    expect(screen.getByText('Community Channel 14')).toBeTruthy()
    expect(screen.getByText(/CivicCast\\media/)).toBeTruthy()
    expect(window.localStorage.getItem('civiccast.staffToken')).toBe('ccst_test_operator_console_token')
  })
})
