import { describe, expect, it, vi } from 'vitest'

import { ApiError } from './api/client'
import { createAppQueryClient } from './queryClient'

/**
 * Field bug (candidate #17): a token dying mid-session (e.g. the admin
 * signing in from another browser) left whatever staff screen was open
 * showing the raw "Invalid staff bearer token" server string, because
 * nothing told the shell's identity check to re-run until the next full
 * page load. createAppQueryClient wires a shared 401 handler so any screen
 * query discovering a dead token re-checks staff identity immediately,
 * which is what lets App.tsx's existing missingStaffSession redirect show a
 * sign-in prompt instead.
 */
describe('createAppQueryClient 401 handling', () => {
  it('invalidates the staff-identity query when an unrelated query gets a 401', async () => {
    const queryClient = createAppQueryClient()
    queryClient.setQueryData(['staff-identity'], { operator_id: 'stale', roles: [] })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await queryClient.fetchQuery({
      queryKey: ['some-staff-screen-data'],
      queryFn: () => {
        throw new ApiError('Request failed: 401 Unauthorized', 401, 'Invalid staff bearer token.')
      },
      retry: false,
    }).catch(() => undefined)

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['staff-identity'] })
  })

  it('does not react to non-401 errors', async () => {
    const queryClient = createAppQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await queryClient.fetchQuery({
      queryKey: ['some-staff-screen-data'],
      queryFn: () => {
        throw new ApiError('Request failed: 500 Internal Server Error', 500, 'Something else broke.')
      },
      retry: false,
    }).catch(() => undefined)

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('does not re-invalidate itself when the staff-identity query is the one that 401s', async () => {
    const queryClient = createAppQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await queryClient.fetchQuery({
      queryKey: ['staff-identity'],
      queryFn: () => {
        throw new ApiError('Request failed: 401 Unauthorized', 401, 'Invalid staff bearer token.')
      },
      retry: false,
    }).catch(() => undefined)

    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})
