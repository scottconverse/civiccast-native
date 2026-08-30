import { QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from './api/client'

/**
 * Build the app's shared QueryClient, including the shell-wide 401 handler.
 *
 * Any /api/staff/* screen query can outlive its bearer token -- most simply
 * because the admin signed in from another browser or device, which still
 * replaces THIS browser's token (civiccast.installer.station_state's
 * login_station_admin keeps that long-standing "signing in here signs you
 * in here" behavior on purpose; only the recovery flow was changed to stop
 * doing this to unrelated sessions). Left alone, the screen that made the
 * failing request renders the raw "Invalid staff bearer token" server
 * string over whatever it was showing (field evidence, candidate #17: CG
 * Designer stayed on screen showing that error like the app had crashed).
 *
 * App.tsx already redirects to a sign-in prompt when its own shell-level
 * staff-identity check comes back 401. This just makes sure that check
 * re-runs the moment ANY OTHER query discovers the token is dead, instead
 * of only at the next full page load -- so the operator lands on a sign-in
 * prompt instead of a broken screen. It skips the identity query itself so
 * a genuine identity-check failure doesn't invalidate-and-refetch itself in
 * a loop.
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
        if (query.queryKey[0] === 'staff-identity') return
        if (error instanceof ApiError && error.status === 401) {
          void queryClient.invalidateQueries({ queryKey: ['staff-identity'] })
        }
      },
    }),
  })
  return queryClient
}
