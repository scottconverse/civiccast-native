import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import type { StaffRole } from './api/staffAccounts'

vi.mock('./screens/ScheduleScreen', () => ({ ScheduleScreen: () => <h1>Schedule</h1> }))
vi.mock('./screens/AssetsScreen', () => ({ AssetsScreen: () => <h1>Assets</h1> }))

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

function CurrentPath() {
  return <output aria-label="Current route">{useLocation().pathname}</output>
}

function renderLogin(roles: StaffRole[], returnTo?: string) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  })
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const identity = { operator_id: 'test-staff', operator_display_name: 'Test Staff', roles }
    const body = url === '/api/staff/auth/login'
      ? { ...identity, access_token: 'ccst_test_login', issued_at: '2026-10-17T00:00:00Z', expires_at: '2026-10-18T00:00:00Z' }
      : url === '/api/staff/auth/me' ? identity
        : url.startsWith('/api/staff/captions/review-items') || url.startsWith('/api/staff/captions/offline-jobs') || url === '/api/staff/assets' ? [] : {}
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { returnTo } }]}>
        <App />
        <CurrentPath />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'test-staff' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  return fetchMock
}

it('lands a records clerk on the usable caption review queue after staff sign-in', async () => {
  const fetchMock = renderLogin(['records_clerk'])
  await waitFor(() => expect(screen.getByLabelText('Current route').textContent).toBe('/review'))
  expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeTruthy()
  expect(await screen.findByText('No caption cues need review.')).toBeTruthy()
  expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith('/api/staff/captions/review-items'))).toBe(true)
  expect(window.localStorage.getItem('civiccast.staffToken')).toBe('ccst_test_login')
})

it.each<[StaffRole[], string]>([
  [['meeting_operator'], '/assets'],
  [['publish_operator'], '/schedule'],
  [['setup_admin'], '/schedule'],
  [['support_admin'], '/schedule'],
  [['records_clerk', 'publish_operator'], '/schedule'],
])('chooses a permitted default for %j', async (roles, path) => {
  renderLogin(roles)
  await waitFor(() => expect(screen.getByLabelText('Current route').textContent).toBe(path))
})

it('preserves an explicit return destination', async () => {
  renderLogin(['records_clerk'], '/assets')
  await waitFor(() => expect(screen.getByLabelText('Current route').textContent).toBe('/assets'))
})
