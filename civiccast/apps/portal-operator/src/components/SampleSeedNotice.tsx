import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  dismissSampleSeedStatus,
  getSampleSeedStatus,
  getStaffIdentity,
  retrySampleSeedStatus,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type { SampleSeedStatus } from '../types/api.generated'

const SAMPLE_SEED_STATUS_QUERY_KEY = ['sample-seed-status'] as const

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

const FAILED_STEP_LABEL: Record<string, string> = {
  ingest: 'creating the sample video',
  package: 'packaging the sample video for playback',
  publish: 'publishing the sample video to the portal',
  schedule: 'creating the starter schedule item',
}

// Presentational only (no data fetching) so it unit-tests without a network.
export function SampleSeedNoticeView({
  status,
  canRetry,
  dismissing,
  retrying,
  retryError,
  dismissError,
  onDismiss,
  onRetry,
}: {
  status: SampleSeedStatus | undefined
  canRetry: boolean
  dismissing?: boolean
  retrying?: boolean
  retryError?: unknown
  dismissError?: unknown
  onDismiss: () => void
  onRetry: () => void
}) {
  if (!status || status.status !== 'failed' || status.dismissed) return null

  const stepLabel = status.failed_step ? FAILED_STEP_LABEL[status.failed_step] : undefined

  return (
    <div
      role="alert"
      aria-label="First-run sample content setup problem"
      className="mx-4 mt-4 grid gap-2 rounded-md p-4 text-sm md:mx-6"
      style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h2 className="m-0 text-sm font-semibold" style={{ color: 'var(--cc-err)' }}>
            CivicCast could not finish first-run sample setup
          </h2>
          <p className="m-0" style={{ color: 'var(--cc-ink)' }}>
            {stepLabel
              ? `Something went wrong while ${stepLabel}: `
              : 'Something went wrong while preparing sample content: '}
            {status.error_message ?? 'an unknown error.'}
          </p>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            Setup itself finished normally -- only the sample video and starter schedule item
            were affected. Add content and a schedule manually from Assets and Schedule, or
            retry sample setup below.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {canRetry && (
            <button
              type="button"
              onClick={onRetry}
              disabled={retrying}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-err)', color: 'var(--cc-on-err, white)' }}
            >
              {retrying ? 'Retrying…' : 'Retry sample setup'}
            </button>
          )}
          <button
            type="button"
            onClick={onDismiss}
            disabled={dismissing}
            aria-label="Dismiss this notice"
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            {dismissing ? 'Dismissing…' : 'Dismiss'}
          </button>
        </div>
      </div>
      {Boolean(retryError) && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-err)' }}>
          Retry failed: {apiMessage(retryError, 'Could not retry sample setup.')}
        </p>
      )}
      {Boolean(dismissError) && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(dismissError, 'Could not dismiss this notice.')}
        </p>
      )}
    </div>
  )
}

/** Global, dismissible operator-console notice for first-run sample seeding failures (audit A-1). */
export function SampleSeedNotice({ enabled = true }: { enabled?: boolean }) {
  const queryClient = useQueryClient()

  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    enabled,
    retry: false,
  })

  const statusQuery = useQuery({
    queryKey: SAMPLE_SEED_STATUS_QUERY_KEY,
    queryFn: getSampleSeedStatus,
    enabled,
    retry: false,
    // Only a freshly-completed setup can still be "pending"; a slow poll here
    // catches that transition to failed/succeeded without the operator having
    // to reload the console.
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? 3000 : false),
  })

  const dismiss = useMutation({
    mutationFn: dismissSampleSeedStatus,
    onSuccess: (data) => {
      queryClient.setQueryData(SAMPLE_SEED_STATUS_QUERY_KEY, data)
    },
  })

  const retry = useMutation({
    mutationFn: retrySampleSeedStatus,
    onSuccess: (data) => {
      queryClient.setQueryData(SAMPLE_SEED_STATUS_QUERY_KEY, data)
      void queryClient.invalidateQueries({ queryKey: ['staff-assets'] })
      void queryClient.invalidateQueries({ queryKey: ['schedule'] })
    },
  })

  // Fail CLOSED: only enable retry once identity is known to hold a role the
  // server's retry endpoint actually accepts. An errored/loading identity is
  // NOT authorized -- the server gate still enforces this either way; this
  // just keeps the button from promising an action that will 403.
  const canRetry =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'setup_admin') ||
      hasOperatorRole(identityQuery.data, 'publish_operator'))

  return (
    <SampleSeedNoticeView
      status={statusQuery.data}
      canRetry={canRetry}
      dismissing={dismiss.isPending}
      retrying={retry.isPending}
      retryError={retry.error}
      dismissError={dismiss.error}
      onDismiss={() => dismiss.mutate()}
      onRetry={() => retry.mutate()}
    />
  )
}
