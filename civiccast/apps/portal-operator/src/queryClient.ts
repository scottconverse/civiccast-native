import { QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError, clearStoredStaffToken, STAFF_SIGNED_OUT_NOTICE_KEY } from './api/client'

/**
 * Build the app's shared QueryClient, including the shell-wide 401 handler.
 *
 * Any /api/staff/* screen query can outlive its bearer token -- e.g. the
 * session was evicted by the bounded concurrent-session cap, or the token
 * predates a station upgrade (as of the 2026-08-30 fratricide fix,
 * civiccast.installer.station_state's login_station_admin APPENDS to a
 * bounded session list, so an ordinary sign-in elsewhere no longer revokes
 * this browser's token). Left alone, the screen that made the
 * failing request renders the raw "Invalid staff bearer token" server
 * string over whatever it was showing (field evidence, candidate #17: CG
 * Designer stayed on screen showing that error like the app had crashed).
 *
 * OWNER DECISION 2026-08-30 (token-fratricide field bug, self-lockout half):
 * the FIRST thing a 401 does here is discard this browser's stored token
 * (clearStoredStaffToken) and record a signed-out notice for the sign-in
 * card. A browser holding a rotated-out/evicted token used to auto-resend
 * it from every polling query, and every one of those 401s spent staff-auth
 * failure budget until the operator was 429-locked out with zero user
 * action. Clearing the token turns all subsequent requests into
 * budget-free missing-credential 401s, so one stale token can never trip
 * the limiter.
 *
 * App.tsx already redirects to a sign-in prompt when its own shell-level
 * staff-identity check comes back 401. This just makes sure that check
 * re-runs the moment ANY OTHER query discovers the token is dead, instead
 * of only at the next full page load -- so the operator lands on a sign-in
 * prompt instead of a broken screen. It skips the identity query itself so
 * a genuine identity-check failure doesn't invalidate-and-refetch itself in
 * a loop.
 *
 * OWNER DECISION 2026-08-30 (audit finding #2, day-one-lockout fix): it
 * also skips re-invalidating identity once identity ALREADY reflects the
 * dead token (status 'error') or is already mid-refetch (fetchStatus
 * 'fetching'). Before this guard, every sibling query on a signed-out
 * console called invalidateQueries on every single 401 -- and TanStack
 * Query v5's invalidateQueries refetches active observers by default, so a
 * console with several failing queries on one screen (the ordinary state
 * of a browser that was never signed in) fired a REAL extra network call
 * to /api/staff/auth/me for every one of them, roughly doubling the
 * staff-auth failure-budget cost of an ordinary signed-out page load on
 * top of each screen's own real query. Identity only needs to be re-
 * checked once per transition from "looked valid" to "looks dead" -- once
 * it is already known dead, further sibling 401s carry no new information
 * for it to learn.
 */
export function createAppQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
    },
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (!(error instanceof ApiError) || error.status !== 401) return
        // A 401 while a token is stored means the server rejected THIS
        // browser's previously-good token. Stop sending it (no auto-retry
        // into the rate limiter) and leave an honest note for the sign-in
        // card. A 401 with no stored token is just a signed-out browser --
        // nothing to clear, nothing to explain.
        if (clearStoredStaffToken()) {
          try {
            window.sessionStorage.setItem(STAFF_SIGNED_OUT_NOTICE_KEY, '1')
          } catch {
            // Storage unavailable -- the sign-in card simply shows no notice.
          }
        }
        if (query.queryKey[0] === 'staff-identity') return
        const identityQuery = queryClient.getQueryCache().find({ queryKey: ['staff-identity'] })
        if (
          identityQuery?.state.status === 'error' ||
          identityQuery?.state.fetchStatus === 'fetching'
        ) {
          return
        }
        void queryClient.invalidateQueries({ queryKey: ['staff-identity'] })
      },
    }),
  })
  return queryClient
}
