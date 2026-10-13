import { afterEach, describe, expect, it, vi } from 'vitest'
import { loginStaffAccount } from './staffAccounts'

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe('staff account login API', () => {
  it('uses the staff-only public login route without forwarding a stale bearer', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'expired-old-session')
    const login = {
      access_token: 'ccst_one-time-token',
      operator_id: 'staff_1',
      operator_display_name: 'Meeting Clerk',
      roles: ['meeting_operator'],
      issued_at: '2026-10-13T12:00:00+00:00',
      expires_at: '2026-10-14T00:00:00+00:00',
    }
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(login), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(loginStaffAccount('clerk', 'station password')).resolves.toEqual(login)

    const [path, request] = fetchMock.mock.calls[0]!
    expect(path).toBe('/api/staff/auth/login')
    expect(request?.headers).not.toHaveProperty('Authorization')
    expect(JSON.parse(String(request?.body))).toEqual({ username: 'clerk', password: 'station password' })
  })
})
