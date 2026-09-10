import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'

import { TopBar } from './TopBar'

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

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}

function renderTopBar(initialPath = '/health') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <TopBar />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...utils, queryClient }
}

function stubSignedInFetch() {
  const calls: Array<{ method: string; url: string; authorization: string | null }> = []
  let signedOut = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const headers = new Headers(init?.headers)
    calls.push({ method, url, authorization: headers.get('Authorization') })
    if (url === '/api/staff/auth/me') {
      if (signedOut) return jsonResponse({ detail: 'Missing Authorization header.' }, 401)
      return jsonResponse({
        operator_id: 'avery',
        operator_display_name: 'Avery Admin',
        token_id: 'station-first-admin',
        scopes: ['admin'],
        roles: ['setup_admin'],
      })
    }
    if (url === '/api/staff/auth/sign-out' && method === 'POST') {
      signedOut = true
      return jsonResponse({
        status: 'signed_out',
        session_revoked: true,
        message: 'Signed out.',
        next_step: 'Sign in again from First Setup when you need the console.',
      })
    }
    if (url === '/api/version') {
      return jsonResponse({ version: '1.0.0-test' })
    }
    return jsonResponse({ detail: `Unhandled ${method} ${url}` }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

describe('TopBar theme control', () => {
  it('uses a recognizable icon instead of an unexplained D/L glyph', () => {
    renderTopBar()

    const toggle = screen.getByRole('button', { name: 'Switch to dark theme' })
    expect(toggle.textContent).toBe('')
    expect(toggle.querySelector('svg')).toBeTruthy()
  })
})

describe('TopBar sign out (2026-09-09 walkthrough: the console had no sign-out)', () => {
  it('shows no Sign out control for a signed-out browser', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Missing Authorization header.' }, 401)),
    )
    renderTopBar()

    await waitFor(() => expect(screen.getByLabelText('Operator')).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('revokes the server session with the stored token, forgets it, drops the cached identity and lands on First Setup', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'ccst_test_token')
    const calls = stubSignedInFetch()
    const { queryClient } = renderTopBar('/health')

    const signOut = await screen.findByRole('button', { name: 'Sign out' })
    expect(screen.getByLabelText('Avery Admin, Setup admin')).toBeTruthy()

    fireEvent.click(signOut)

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/setup')
    })
    const signOutCall = calls.find((call) => call.url === '/api/staff/auth/sign-out')
    expect(signOutCall?.method).toBe('POST')
    // The server must be told which session to end BEFORE the browser forgets it.
    expect(signOutCall?.authorization).toBe('Bearer ccst_test_token')
    expect(window.localStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(window.sessionStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(queryClient.getQueryData(['staff-identity'])).toBeUndefined()
  })

  it('still forgets the token and leaves when the station cannot be reached', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'ccst_test_token')
    let identityServed = false
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/staff/auth/me' && !identityServed) {
          identityServed = true
          return jsonResponse({
            operator_id: 'avery',
            operator_display_name: 'Avery Admin',
            roles: ['setup_admin'],
          })
        }
        if (url === '/api/staff/auth/sign-out' && init?.method === 'POST') {
          throw new TypeError('Failed to fetch')
        }
        return jsonResponse({ detail: 'not stubbed' }, 404)
      }),
    )
    renderTopBar('/health')

    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/setup')
    })
    expect(window.localStorage.getItem('civiccast.staffToken')).toBeNull()
  })

  it('holds Sign out while the one-time recovery kit is still waiting to be confirmed', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'ccst_test_token')
    window.sessionStorage.setItem(
      'civiccast.pendingRecoveryKit',
      JSON.stringify({
        setup: { recovery_kit: { recovery_codes: ['CC-ONE'] }, profile: {} },
        admin_password: 'correct horse battery staple',
        stored_at: Date.now(),
      }),
    )
    const calls = stubSignedInFetch()
    renderTopBar('/setup')

    const signOut = (await screen.findByRole('button', { name: 'Sign out' })) as HTMLButtonElement
    expect(signOut.disabled).toBe(true)
    expect(signOut.getAttribute('title')).toMatch(/recovery kit/i)

    fireEvent.click(signOut)
    expect(calls.some((call) => call.url === '/api/staff/auth/sign-out')).toBe(false)
    expect(window.localStorage.getItem('civiccast.staffToken')).toBe('ccst_test_token')
  })
})
