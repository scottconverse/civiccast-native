import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { BackupSetupPanel, CostForecastPanel, R2ConciergeCard, SetupScreen } from './SetupScreen'

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
      <MemoryRouter>
        <SetupScreen />
      </MemoryRouter>
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
      <MemoryRouter>
        <R2ConciergeCard canManageProviders={canManageProviders} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderBackupSetupPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BackupSetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderCostForecastPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CostForecastPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CostForecastPanel', () => {
  it('never prints an invented dollar figure for CDN bandwidth cost', () => {
    renderCostForecastPanel()
    // The old behavior computed hours * meetings * viewers * an unsourced
    // $0.005/GB constant and printed it as "$20.00". No "$<number>" tile
    // should exist anywhere in this panel any more.
    expect(screen.queryByText(/^\$\d/)).toBeNull()
    expect(screen.getByText('Varies by provider')).toBeTruthy()
    expect(screen.getByText(/cloudflare r2 is free/i)).toBeTruthy()
  })

  it('names Cloudflare R2 as the $0-egress provider, sourced, not estimated', () => {
    renderCostForecastPanel()
    expect(
      screen.getByText(/charges \$0 for egress.*not a civiccast estimate/i),
    ).toBeTruthy()
  })

  it('links to the manual\'s CDN cost estimate section', () => {
    renderCostForecastPanel()
    const link = screen.getByRole('link', { name: /read more in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#cdn-cost-estimate')
  })

  it('still computes storage and bandwidth GB from the entered numbers', () => {
    renderCostForecastPanel()
    fireEvent.change(screen.getByLabelText(/hours per meeting/i), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText(/meetings per month/i), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText(/average viewers/i), { target: { value: '250' } })
    expect(screen.getByText('16 GB')).toBeTruthy()
    expect(screen.getByText('4000 GB')).toBeTruthy()
  })
})

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
          database_configured: true,
          database_kind: 'sqlite',
          database_host: null,
          database_port: null,
          database_name: null,
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
    window.history.replaceState(null, '', '/operator/#/setup')
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:civiccast-recovery-kit'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.spyOn(window, 'print').mockImplementation(() => {})
    // Capture what the "Save kit" download actually contains -- reading a
    // Blob's content back out is unreliable across jsdom/undici realms in
    // this test environment, so record the parts a Blob was built from
    // instead of round-tripping through the Blob object itself.
    const savedBlobParts: string[] = []
    const RealBlob = window.Blob
    class RecordingBlob extends RealBlob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        savedBlobParts.push(String(parts[0]))
        super(parts, options)
      }
    }
    vi.stubGlobal('Blob', RecordingBlob)

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
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: setupComplete ? 'Open System Health.' : 'Create the first admin.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({
          status: 'ready',
          database_configured: true,
          database_kind: 'sqlite',
          database_host: null,
          database_port: null,
          database_name: null,
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
          operator_console_url: 'http://127.0.0.1:8000/operator/',
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
          operator_console_url: 'http://127.0.0.1:8000/operator/',
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

    // Field bug fix (candidate #17): the kit must show the routine admin
    // password, not just the emergency recovery codes -- otherwise the
    // holder has a username and 8 codes but no way to sign in normally.
    expect(screen.getByText('correct horse battery staple')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save kit' }))
    expect(savedBlobParts.join('\n')).toContain('correct horse battery staple')

    fireEvent.click(screen.getByRole('checkbox', { name: /I have saved or printed this kit/ }))
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

  it('does not unlock the acknowledge checkbox merely because Print kit was clicked, before the print dialog closes', async () => {
    window.history.replaceState(null, '', '/operator/#/setup')
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    // Simulate the real browser contract: window.print() returns as soon as
    // the OS dialog opens, well before the operator dismisses it (by
    // printing OR cancelling). 'afterprint' does not fire synchronously.
    vi.spyOn(window, 'print').mockImplementation(() => {})

    let setupComplete = false
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
          recovery_kit_acknowledged: false,
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: setupComplete ? 'Open System Health.' : 'Create the first admin.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({
          status: 'ready',
          database_configured: true,
          database_kind: 'sqlite',
          database_host: null,
          database_port: null,
          database_name: null,
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
          roles: ['setup_admin'],
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
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          operator_console_token: 'ccst_test_operator_console_token',
          next_step: 'Save the recovery kit.',
        })
      }
      return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()

    await screen.findByText('Station name')
    fireEvent.change(inputById('station_name'), { target: { value: profile.station_name } })
    fireEvent.change(inputById('admin_display_name'), { target: { value: profile.admin_display_name } })
    fireEvent.change(inputById('admin_username'), { target: { value: profile.admin_username } })
    fireEvent.change(inputById('admin_password'), { target: { value: 'correct horse battery staple' } })
    fireEvent.change(inputById('confirm_password'), { target: { value: 'correct horse battery staple' } })
    fireEvent.change(inputById('recovery_kit_destination'), {
      target: { value: 'printed and stored offline' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create first admin' }))
    expect(await screen.findByText('Recovery kit ready')).toBeTruthy()

    // CRITICAL regression check: clicking Print kit alone (dialog not yet
    // dismissed) must NOT unlock the "I have saved or printed this kit"
    // checkbox -- otherwise cancelling the OS print dialog still lets the
    // operator leave the only screen showing the admin password + recovery
    // codes without ever saving them.
    fireEvent.click(screen.getByRole('button', { name: 'Print kit' }))
    expect(window.print).toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: /I have saved or printed this kit/ })).toHaveProperty(
      'disabled',
      true,
    )
    expect(screen.getByText('Use Print kit or Save kit first.')).toBeTruthy()

    // Only once the browser reports the print dialog actually closed
    // ('afterprint') does the checkbox unlock.
    fireEvent(window, new Event('afterprint'))
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /I have saved or printed this kit/ })).toHaveProperty(
        'disabled',
        false,
      )
    })
  })
})

describe('SetupScreen returning-operator sign-in', () => {
  function stubReturningOperatorFetch(overrides: {
    onRecover?: (body: unknown) => Promise<Response>
  } = {}) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/setup/station-state') {
        return jsonResponse({
          status: 'complete',
          setup_complete: true,
          profile,
          recovery_kit_created: true,
          recovery_kit_id: 'rk_test',
          recovery_kit_acknowledged: true,
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: 'Open System Health.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({
          status: 'ready',
          database_configured: true,
          database_kind: 'sqlite',
          database_host: null,
          database_port: null,
          database_name: null,
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
        return jsonResponse({ detail: 'Missing Authorization header. Use Bearer <staff-token>.' }, 401)
      }
      if (url === '/api/setup/recover' && method === 'POST') {
        if (overrides.onRecover) return overrides.onRecover(JSON.parse(String(init?.body)))
        return jsonResponse({ detail: 'Invalid recovery code or admin username.' }, 401)
      }
      return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
    })
  }

  it('shows the actual server message on a failed recovery attempt, not a generic sign-in-elsewhere prompt', async () => {
    window.history.replaceState(null, '', '/operator/#/setup')
    vi.stubGlobal('fetch', stubReturningOperatorFetch())

    renderSetupScreen()

    await screen.findByText('Use recovery code')
    // Field bug fix (candidate #17): a wrong/expired recovery code used to
    // render the generic "Could not verify your recovery authority... ask a
    // setup admin for a fresh operator-console link" message, which makes no
    // sense when recovery IS the last-resort path because there is no other
    // admin to ask. It must show the real server reason instead.
    fireEvent.change(inputById('recover-admin-username'), { target: { value: 'testadmin' } })
    fireEvent.change(inputById('recover-code'), { target: { value: 'CC-WRONGCODE' } })
    fireEvent.change(inputById('recover-new-password'), {
      target: { value: 'brand new password twelve' },
    })
    fireEvent.change(inputById('recover-confirm-new-password'), {
      target: { value: 'brand new password twelve' },
    })
    // Recovery permanently consumes one of only 8 codes, so the first click
    // only arms a confirmation; the second click actually submits.
    fireEvent.click(screen.getByRole('button', { name: 'Recover account' }))
    fireEvent.click(screen.getByRole('button', { name: /Confirm/ }))

    expect(await screen.findByText('Invalid recovery code or admin username.')).toBeTruthy()
    expect(screen.queryByText(/ask a setup admin/)).toBeNull()
  })

  it('requires a matching confirm-password and an explicit confirm click before consuming a recovery code', async () => {
    window.history.replaceState(null, '', '/operator/#/setup')
    let recoverCalls = 0
    vi.stubGlobal(
      'fetch',
      stubReturningOperatorFetch({
        onRecover: async (body) => {
          recoverCalls += 1
          return jsonResponse({
            status: 'complete',
            profile,
            operator_console_url: 'http://127.0.0.1:8000/operator/',
            operator_console_token: 'ccst_test_operator_console_token',
            next_step: 'Open System Health.',
            _received: body,
          })
        },
      }),
    )

    renderSetupScreen()

    await screen.findByText('Use recovery code')
    fireEvent.change(inputById('recover-admin-username'), { target: { value: 'testadmin' } })
    fireEvent.change(inputById('recover-code'), { target: { value: 'CC-ONE' } })
    fireEvent.change(inputById('recover-new-password'), {
      target: { value: 'brand new password twelve' },
    })
    fireEvent.change(inputById('recover-confirm-new-password'), {
      target: { value: 'does not match' },
    })

    expect(screen.getByText('Passwords do not match.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Recover account' })).toHaveProperty('disabled', true)

    fireEvent.change(inputById('recover-confirm-new-password'), {
      target: { value: 'brand new password twelve' },
    })

    // First click only arms the destructive confirmation -- it must not
    // consume the recovery code by itself.
    fireEvent.click(screen.getByRole('button', { name: 'Recover account' }))
    expect(
      screen.getByText(/This permanently consumes one recovery code/),
    ).toBeTruthy()
    expect(recoverCalls).toBe(0)

    fireEvent.click(screen.getByRole('button', { name: /Confirm — consume recovery code/ }))
    await waitFor(() => expect(recoverCalls).toBe(1))
  })

  it('warns that recovery is an emergency-only path that spends a limited code', async () => {
    window.history.replaceState(null, '', '/operator/#/setup')
    vi.stubGlobal('fetch', stubReturningOperatorFetch())

    renderSetupScreen()

    await screen.findByText('Use recovery code')
    expect(screen.getByText(/Emergency only/)).toBeTruthy()
    expect(screen.getByText(/permanently consumes one of your 8 printed codes/)).toBeTruthy()
    expect(screen.getByText(/Every other browser or device already signed in stays signed in/)).toBeTruthy()
  })
})

describe('SetupScreen signed-out after setup (setup API requires the staff token)', () => {
  it('renders sign-in and recovery from the reduced station-state body and never asks for storage', async () => {
    const requestedUrls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      requestedUrls.push(`${method} ${url}`)
      if (url === '/api/setup/station-state') {
        // Exactly what GET /api/setup/station-state returns to a caller with
        // no Authorization header once setup is complete: no profile, no
        // admin username, no recovery kit id, acknowledgement withheld.
        return jsonResponse({
          status: 'complete',
          setup_complete: true,
          station_name: 'Pinegrove School Board',
          profile: null,
          recovery_kit_created: false,
          recovery_kit_id: null,
          recovery_kit_acknowledged: null,
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: 'Sign in with the local admin password to continue.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({ detail: 'Setup is complete. Sign in first.' }, 401)
      }
      return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()

    expect(await screen.findByText('Setup complete')).toBeTruthy()
    expect(
      screen.getByText(/Pinegrove School Board already has a first admin and recovery kit/),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
    expect(screen.getByText('Use recovery code')).toBeTruthy()
    // recovery_kit_acknowledged is null (withheld), not false: no alert that
    // would invite a signed-out visitor to click an endpoint they cannot use.
    expect(screen.queryByText('Recovery kit never confirmed')).toBeNull()
    expect(screen.queryByText('First-run defaults')).toBeNull()
    expect(requestedUrls).not.toContain('GET /api/setup/storage')
    expect(requestedUrls).not.toContain('GET /api/staff/auth/me')
  })
})

describe('SetupScreen stale staff token (HIGH 2, hostile review of PR #215)', () => {
  const signedOutBody = {
    status: 'complete',
    setup_complete: true,
    station_name: 'Pinegrove School Board',
    profile: null,
    recovery_kit_created: false,
    recovery_kit_id: null,
    recovery_kit_acknowledged: null,
    operator_console_url: 'http://127.0.0.1:8000/operator/',
    next_step: 'Sign in with the local admin password to continue.',
  }

  function authorizationOf(init?: RequestInit): string | null {
    const headers = init?.headers
    if (!headers) return null
    if (headers instanceof Headers) return headers.get('Authorization')
    if (Array.isArray(headers)) {
      const pair = headers.find(([name]) => name.toLowerCase() === 'authorization')
      return pair ? pair[1] : null
    }
    const record = headers as Record<string, string>
    return record.Authorization ?? record.authorization ?? null
  }

  it('drops a token the server rejects and lands on a usable sign-in card instead of an error dead-end', async () => {
    // An operator whose console token expired (evicted under the session
    // cap, or the station's sign-in state reset) still has it stored.
    window.localStorage.setItem('civiccast.staffToken', 'ccst_stale_token')
    window.sessionStorage.setItem('civiccast.staffToken', 'ccst_stale_token')
    const requestedUrls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const authorization = authorizationOf(init)
      requestedUrls.push(`${url} ${authorization ?? '(no token)'}`)
      if (url === '/api/setup/station-state') {
        // civiccast/installer/router.py public_station_state: a present-but-
        // invalid token is a 401 so the browser learns to drop it; no token
        // at all is the signed-out view.
        if (authorization) {
          return Promise.resolve(
            new Response(JSON.stringify({ detail: 'Invalid staff bearer token.' }), {
              status: 401,
              headers: { 'Content-Type': 'application/json', 'WWW-Authenticate': 'Bearer' },
            }),
          )
        }
        return jsonResponse(signedOutBody)
      }
      if (url === '/api/staff/auth/me') {
        return jsonResponse({ detail: 'Invalid staff bearer token.' }, 401)
      }
      return jsonResponse({ detail: `Unhandled GET ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()

    // The sign-in form is reachable: the operator is not stuck on
    // "Could not read setup state. Invalid staff bearer token." with no
    // way forward.
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy()
    expect(inputById('login-admin-username')).toBeTruthy()
    expect(screen.queryByText(/Could not read setup state/)).toBeNull()
    // The dead token is gone from both storages, so nothing re-sends it.
    expect(window.localStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(window.sessionStorage.getItem('civiccast.staffToken')).toBeNull()
    // The operator is told why they are looking at a sign-in card.
    expect(screen.getByText('You were signed out')).toBeTruthy()
    // The state was re-read WITHOUT the stale token to get here.
    expect(requestedUrls).toContain('/api/setup/station-state (no token)')
  })

  it('"Sign in again" on the 401 card recovers while the station KEEPS rejecting the token it could not clear automatically', async () => {
    // MINOR-1 (hostile review of PR #215, round 2): a token the automatic
    // path cannot discard -- the test-only injected one -- was re-sent by
    // the button, so the same 401 card came straight back. The station never
    // starts accepting the token in this test; the button must stop sending
    // it and land on the sign-in form from the signed-out view.
    window.__CIVICCAST_STAFF_TOKEN__ = 'ccst_injected_stale'
    try {
      const requestedUrls: string[] = []
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const authorization = authorizationOf(init)
        requestedUrls.push(`${url} ${authorization ?? '(no token)'}`)
        if (url === '/api/setup/station-state') {
          if (authorization) {
            return jsonResponse({ detail: 'Invalid staff bearer token.' }, 401)
          }
          return jsonResponse(signedOutBody)
        }
        if (url === '/api/staff/auth/me') {
          return jsonResponse({ detail: 'Invalid staff bearer token.' }, 401)
        }
        return jsonResponse({ detail: `Unhandled GET ${url}` }, 404)
      })
      vi.stubGlobal('fetch', fetchMock)

      renderSetupScreen()

      const again = await screen.findByRole('button', { name: 'Sign in again' })
      expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull()
      fireEvent.click(again)
      expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy()
      expect(inputById('login-admin-username')).toBeTruthy()
      expect(screen.queryByRole('button', { name: 'Sign in again' })).toBeNull()
      // The recovery read went out WITHOUT the rejected token.
      expect(requestedUrls).toContain('/api/setup/station-state (no token)')
      expect(screen.getByText('You were signed out')).toBeTruthy()
    } finally {
      delete window.__CIVICCAST_STAFF_TOKEN__
    }
  })

  it('still offers the admin sign-in form when station-state is rate-limited (429)', async () => {
    // MINOR-4 (hostile review of PR #215, round 2): /api/setup/station-state
    // spends a per-request budget, and the stale-token recovery costs two
    // reads, so a 429 there is likelier -- and it rendered the generic
    // "Could not read setup state" card with no way to sign in. /api/setup/
    // login is budgeted separately (per IP AND path), so the operator can
    // still sign in from a station-state 429 if the form is on the card.
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/setup/station-state') {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail:
                'Too many sign-in attempts from this station. Wait 42 seconds, then try again with the correct password, or use a printed recovery code.',
            }),
            {
              status: 429,
              headers: { 'Content-Type': 'application/json', 'Retry-After': '42' },
            },
          ),
        )
      }
      if (url === '/api/setup/login' && init?.method === 'POST') {
        return jsonResponse({
          status: 'authenticated',
          profile,
          operator_console_token: 'ccst_fresh_token',
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: 'Open the operator console.',
        })
      }
      return jsonResponse({ detail: `Unhandled ${init?.method ?? 'GET'} ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()

    expect(await screen.findByText(/Wait 42 seconds/)).toBeTruthy()
    const signIn = await screen.findByRole('button', { name: 'Sign in' })
    fireEvent.change(inputById('login-admin-username'), { target: { value: 'avery' } })
    fireEvent.change(inputById('login-admin-password'), {
      target: { value: 'correct horse battery staple' },
    })
    fireEvent.click(signIn)
    await waitFor(() =>
      expect(window.localStorage.getItem('civiccast.staffToken')).toBe('ccst_fresh_token'),
    )
    expect(fetchMock.mock.calls.some(([input]) => String(input) === '/api/setup/login')).toBe(true)
  })
})

describe('SetupScreen staff-identity gating (Finding MINOR-1)', () => {
  it('never calls /api/staff/auth/me for a signed-out visitor with no stored token', async () => {
    const requestedUrls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      requestedUrls.push(url)
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
          database_configured: true,
          database_kind: 'sqlite',
          database_host: null,
          database_port: null,
          database_name: null,
          database_path: '/tmp/civiccast.db',
          upload_dir: '/tmp/uploads',
          storage_dir: '/tmp',
          migrations_applied: true,
          configured_at: '2026-06-28T00:00:00Z',
          operator_message: 'Storage ready',
          next_step: 'Create the first admin.',
        })
      }
      return jsonResponse({ detail: `Unhandled GET ${url}` }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetupScreen()
    await screen.findByText('Station name')

    // A fresh browser with no stored staff token has nothing to send
    // /api/staff/auth/me and the request is guaranteed to 401 -- it must
    // simply not be sent, not sent-and-tolerated. Prior to this fix, this
    // fired on every fresh boot regardless of token presence (console 401s
    // on the very first First Setup paint, per the 2026-09-03 walkthrough).
    expect(requestedUrls).not.toContain('/api/staff/auth/me')
  })
})
