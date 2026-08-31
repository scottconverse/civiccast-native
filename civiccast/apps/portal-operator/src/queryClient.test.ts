import { QueryObserver } from '@tanstack/react-query'
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

  /**
   * Day-one-lockout audit finding #2: TanStack Query v5's invalidateQueries
   * refetches active observers by default, so the ORIGINAL handler above
   * invalidated (and therefore re-fetched) staff-identity on EVERY sibling
   * 401 -- even once identity itself already reflected the exact same dead
   * token. On a signed-out console with several failing queries on one
   * screen (its ordinary state, never having signed in), that meant one
   * real extra network call to /api/staff/auth/me per sibling failure,
   * roughly doubling the staff-auth failure budget an ordinary page load
   * spent. These tests pin the fix: re-check identity once per session
   * (the first sibling 401 after identity looked valid or unfetched), never
   * again while identity already reflects the failure.
   */
  it('does not re-invalidate identity once identity already reflects the dead token', async () => {
    const queryClient = createAppQueryClient()

    // Identity itself fails with 401 the ordinary way first (as it does on
    // a signed-out console), so its own query state is already 'error'.
    await queryClient
      .fetchQuery({
        queryKey: ['staff-identity'],
        queryFn: () => {
          throw new ApiError(
            'Request failed: 401 Unauthorized',
            401,
            'Missing Authorization header. Use Bearer <staff-token>.',
          )
        },
        retry: false,
      })
      .catch(() => undefined)

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    // A sibling query on the same dead session also 401s -- this carries no
    // new information for identity, which already knows the token is dead.
    await queryClient
      .fetchQuery({
        queryKey: ['some-other-staff-screen-data'],
        queryFn: () => {
          throw new ApiError('Request failed: 401 Unauthorized', 401, 'Invalid staff bearer token.')
        },
        retry: false,
      })
      .catch(() => undefined)

    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('fetches staff identity at most once across several sibling 401s on a dead session', async () => {
    // Mirrors the live repro: loading the console, then #/help, then
    // #/assets -- three ordinary page loads on a browser that was never
    // signed in -- each mounting its own screen queries that all 401.
    const queryClient = createAppQueryClient()
    const identityFetch = vi.fn(async () => {
      throw new ApiError(
        'Request failed: 401 Unauthorized',
        401,
        'Missing Authorization header. Use Bearer <staff-token>.',
      )
    })

    // A mounted QueryObserver, matching how App.tsx's shell-level
    // useQuery(['staff-identity']) actually keeps the query active.
    const observer = new QueryObserver(queryClient, {
      queryKey: ['staff-identity'],
      queryFn: identityFetch,
      retry: false,
    })
    const unsubscribe = observer.subscribe(() => {})

    await vi.waitFor(() => expect(identityFetch).toHaveBeenCalledTimes(1))

    for (let screen = 0; screen < 3; screen += 1) {
      await queryClient
        .fetchQuery({
          queryKey: ['sibling-screen-data', screen],
          queryFn: () => {
            throw new ApiError(
              'Request failed: 401 Unauthorized',
              401,
              'Invalid staff bearer token.',
            )
          },
          retry: false,
        })
        .catch(() => undefined)
    }

    unsubscribe()
    expect(identityFetch).toHaveBeenCalledTimes(1)
  })

  /**
   * Token-fratricide field bug, self-lockout half (owner-verified
   * 2026-08-30): a browser holding a token the server had stopped accepting
   * kept auto-resending it from every polling query. Each of those 401s
   * spent staff-auth failure budget until the operator was 429-locked out
   * ("Too many failed attempts... wait N seconds") with zero user action.
   * The fix: the FIRST rejected 401 discards the stored token, so every
   * subsequent request goes out with no Authorization header at all -- the
   * middleware's budget-free missing-credential path -- and leaves a
   * sessionStorage notice for the sign-in card to explain the sign-out.
   */
  it('discards the stored staff token and records a signed-out notice on a 401', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'ccst_previously-good-token')
    window.sessionStorage.setItem('civiccast.staffToken', 'ccst_previously-good-token')
    const queryClient = createAppQueryClient()

    await queryClient
      .fetchQuery({
        queryKey: ['some-staff-screen-data'],
        queryFn: () => {
          throw new ApiError('Request failed: 401 Unauthorized', 401, 'Invalid staff bearer token.')
        },
        retry: false,
      })
      .catch(() => undefined)

    expect(window.localStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(window.sessionStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(window.sessionStorage.getItem('civiccast.staffSignedOutNotice')).toBe('1')
    window.sessionStorage.removeItem('civiccast.staffSignedOutNotice')
  })

  it('records no signed-out notice for a browser that never had a stored token', async () => {
    window.localStorage.removeItem('civiccast.staffToken')
    window.sessionStorage.removeItem('civiccast.staffToken')
    window.sessionStorage.removeItem('civiccast.staffSignedOutNotice')
    const queryClient = createAppQueryClient()

    await queryClient
      .fetchQuery({
        queryKey: ['some-staff-screen-data'],
        queryFn: () => {
          throw new ApiError(
            'Request failed: 401 Unauthorized',
            401,
            'Missing Authorization header. Use Bearer <staff-token>.',
          )
        },
        retry: false,
      })
      .catch(() => undefined)

    expect(window.sessionStorage.getItem('civiccast.staffSignedOutNotice')).toBeNull()
  })

  it('discards the token even when the identity query itself is the one that 401s', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'ccst_previously-good-token')
    const queryClient = createAppQueryClient()

    await queryClient
      .fetchQuery({
        queryKey: ['staff-identity'],
        queryFn: () => {
          throw new ApiError('Request failed: 401 Unauthorized', 401, 'Invalid staff bearer token.')
        },
        retry: false,
      })
      .catch(() => undefined)

    expect(window.localStorage.getItem('civiccast.staffToken')).toBeNull()
    expect(window.sessionStorage.getItem('civiccast.staffSignedOutNotice')).toBe('1')
    window.sessionStorage.removeItem('civiccast.staffSignedOutNotice')
  })
})
