import { describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// The container derives the privileged `canInstall` gate from the identity query;
// the leaf TsduckStatusView is tested elsewhere. Mock the client so this exercises
// the real fail-closed derivation (T3).
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getStaffIdentity: vi.fn(),
  getTsduckStatus: vi.fn(),
  installTsduck: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import { getStaffIdentity, getTsduckStatus } from '../api/client'
import { CableVerificationCard } from './CableVerificationCard'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_display_name: 'Dana', roles } as unknown as StaffIdentityResponse
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CableVerificationCard />
    </QueryClientProvider>,
  )
}

describe('CableVerificationCard container role-gating (fail-closed)', () => {
  it('disables Enable for a non-admin operator', async () => {
    vi.mocked(getTsduckStatus).mockResolvedValue({ installed: false, install_hint: '' })
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderCard()
    const btn = (await findByText('Enable cable verification')) as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(true))
  })

  it('enables Enable for a setup admin', async () => {
    vi.mocked(getTsduckStatus).mockResolvedValue({ installed: false, install_hint: '' })
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByText } = renderCard()
    const btn = (await findByText('Enable cable verification')) as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(false))
  })

  it('disables Enable when identity fails to load (fail-closed, not fail-open)', async () => {
    vi.mocked(getTsduckStatus).mockResolvedValue({ installed: false, install_hint: '' })
    vi.mocked(getStaffIdentity).mockRejectedValue(new Error('401 unauthorized'))
    const { findByText } = renderCard()
    const btn = (await findByText('Enable cable verification')) as HTMLButtonElement
    await waitFor(() => expect(btn.disabled).toBe(true))
  })
})
