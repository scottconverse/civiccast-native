import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import {
  StaffAccountsScreen,
} from './StaffAccountsScreen'
import type { StaffAccountsApi, StaffLoginResult } from '../api/staffAccounts'
import { StaffLoginForm } from './StaffLoginForm'

afterEach(cleanup)

const loginResult: StaffLoginResult = {
  access_token: 'ccst_one-time-token',
  operator_id: 'staff_1',
  operator_display_name: 'Meeting Clerk',
  roles: ['meeting_operator'],
  issued_at: '2026-10-13T12:00:00+00:00',
  expires_at: '2026-10-14T00:00:00+00:00',
}

function renderAccounts(api: StaffAccountsApi) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <StaffAccountsScreen api={api} />
    </QueryClientProvider>,
  )
}

describe('StaffAccountsScreen', () => {
  it('lets an administrator revoke a saved session', async () => {
    const api: StaffAccountsApi = {
      listAccounts: vi.fn().mockResolvedValue([
        {
          operator_id: 'first-admin',
          username: 'avery',
          display_name: 'Avery Admin',
          roles: ['setup_admin'],
          enabled: true,
          account_type: 'first_admin',
          immutable: true,
        },
      ]),
      createAccount: vi.fn(),
      updateAccount: vi.fn(),
      resetPassword: vi.fn(),
      listSessions: vi.fn().mockResolvedValue([
        {
          session_id: 'sess_1',
          operator_id: 'staff_1',
          operator_display_name: 'Meeting Clerk',
          roles: ['meeting_operator'],
          source: 'staff-login',
          issued_at: '2026-10-13T12:00:00+00:00',
          expires_at: '2026-10-14T00:00:00+00:00',
          expired: false,
          current: false,
        },
      ]),
      revokeSession: vi.fn().mockResolvedValue(undefined),
    }
    const { findByRole } = renderAccounts(api)

    fireEvent.click(await findByRole('button', { name: 'Revoke session' }))

    await waitFor(() => expect(api.revokeSession).toHaveBeenCalledWith('sess_1'))
  })
})

describe('StaffLoginForm', () => {
  it('passes credentials to the integration hook and returns the issued session', async () => {
    const onLogin = vi.fn().mockResolvedValue(loginResult)
    const onAuthenticated = vi.fn()
    const { getByLabelText, getByRole } = render(
      <StaffLoginForm onLogin={onLogin} onAuthenticated={onAuthenticated} />,
    )

    fireEvent.change(getByLabelText('Username'), { target: { value: ' clerk ' } })
    fireEvent.change(getByLabelText('Password'), { target: { value: 'temporary password' } })
    fireEvent.click(getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith('clerk', 'temporary password'))
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(loginResult))
  })
})
