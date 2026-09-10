// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * While a first-setup recovery kit is waiting to be confirmed, the shell
 * bounces every other route back to First Setup (2026-09-09 beta.5
 * walkthrough: leaving the screen lost the one-time codes for good).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import App from './App'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
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

const profile = {
  station_name: 'CivicCast Test Station',
  admin_display_name: 'Test Admin',
  admin_username: 'testadmin',
  default_channel_id: 'gov-ch12',
  public_base_url: null,
  station_timezone: 'America/Denver',
  storage_locations: { media_library: 'C:\\x', recordings: 'C:\\y', backups: 'C:\\z' },
  channel_count: 0,
  channel_profiles: [],
  sample_content_enabled: false,
  initial_schedule_enabled: false,
  default_roles: ['setup_admin'],
  operation_mode: 'test',
  dashboard_ready_state: 'not_ready',
  recovery_kit_id: 'rk_test',
  recovery_kit_generated_at: '2026-06-28T00:00:00Z',
}

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/setup/station-state') {
        return jsonResponse({
          status: 'complete',
          setup_complete: true,
          profile,
          recovery_kit_created: true,
          recovery_kit_id: 'rk_test',
          recovery_kit_acknowledged: false,
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          next_step: 'Save the recovery kit.',
        })
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({ status: 'ready', message: 'ready', next_step: 'Create the first admin.' })
      }
      if (url === '/api/staff/auth/me') {
        return jsonResponse({ operator_id: 'testadmin', operator_display_name: 'Test Admin', roles: ['setup_admin'] })
      }
      return jsonResponse({ detail: `Unhandled ${url}` }, 404)
    }),
  )
}

describe('App recovery-kit route guard', () => {
  it('bounces a direct visit to another route back to First Setup and renders the stored kit', async () => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    })
    window.localStorage.setItem('civiccast.staffToken', 'ccst_test_operator_console_token')
    window.sessionStorage.setItem(
      'civiccast.pendingRecoveryKit',
      JSON.stringify({
        setup: {
          status: 'complete',
          profile,
          recovery_kit: {
            kit_id: 'rk_test',
            generated_at: '2026-06-28T00:00:00Z',
            station_name: profile.station_name,
            admin_username: profile.admin_username,
            recovery_codes: ['CC-ONE', 'CC-TWO'],
            instructions: ['Store the kit offline.'],
            excludes: [],
          },
          operator_console_url: 'http://127.0.0.1:8000/operator/',
          operator_console_token: 'ccst_test_operator_console_token',
          next_step: 'Save the recovery kit.',
        },
        admin_password: 'correct horse battery staple',
        stored_at: Date.now(),
      }),
    )
    stubFetch()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/health']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Recovery kit ready')).toBeTruthy()
    expect(screen.getByText('CC-ONE')).toBeTruthy()
    // The shell's navigation is held for the same reason.
    const readiness = screen.getByRole('button', { name: 'Readiness' }) as HTMLButtonElement
    expect(readiness.disabled).toBe(true)
  })
})
