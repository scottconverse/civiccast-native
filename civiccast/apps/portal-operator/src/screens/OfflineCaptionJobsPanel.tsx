import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  getStaffIdentity,
  listOfflineCaptionJobs,
  retryOfflineCaptionJob,
} from '../api/client'
import type { OfflineCaptionJobRecord } from '../types/api.generated'
import { hasRole } from './contribution-format'

const RETRY_ROLES = ['records_clerk']

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function stateTone(state: OfflineCaptionJobRecord['state']): { bg: string; label: string } {
  switch (state) {
    case 'complete':
      return { bg: 'var(--cc-ok-soft)', label: 'Complete' }
    case 'failed':
      return { bg: 'var(--cc-err-soft)', label: 'Failed' }
    case 'awaiting_review':
      return { bg: 'var(--cc-warn-soft)', label: 'Awaiting review' }
    default:
      return { bg: 'var(--cc-surface-3)', label: 'Pending' }
  }
}

// Presentational only (no data fetching, no mutation) so the row states —
// loading / success / error / confirm — unit-test without a network.
export function OfflineCaptionJobsView({
  jobs,
  loading,
  error,
  canRetry,
  retryingJobId,
  retriedJobId,
  retryError,
  onRetry,
}: {
  jobs: OfflineCaptionJobRecord[] | undefined
  loading?: boolean
  error?: unknown
  canRetry: boolean
  retryingJobId?: string | null
  retriedJobId?: string | null
  retryError?: { jobId: string; error: unknown } | null
  onRetry: (jobId: string) => void
}) {
  const rows = jobs ?? []
  return (
    <section
      aria-label="Offline caption jobs"
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Offline caption jobs</h2>
        {loading && (
          <span className="cc-mono rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            checking
          </span>
        )}
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        The background job that transcribes this recording for offline (VOD) captions. A failed
        job can be given a fresh attempt without re-approving publish.
      </p>
      {Boolean(error) && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Offline caption jobs could not load.')}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          No offline caption jobs for this recording yet.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-auto">
          <table className="w-full border-collapse text-sm" aria-label="Offline caption job rows">
            <thead>
              <tr className="text-left text-xs uppercase" style={{ color: 'var(--cc-ink-3)' }}>
                <th scope="col" className="py-1 pr-3 font-medium">State</th>
                <th scope="col" className="py-1 pr-3 font-medium">Attempts</th>
                <th scope="col" className="py-1 pr-3 font-medium">Last error</th>
                <th scope="col" className="py-1 pr-3 font-medium">Updated</th>
                <th scope="col" className="py-1 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((job) => {
                const tone = stateTone(job.state)
                const isRetrying = retryingJobId === job.job_id
                const justRetried = retriedJobId === job.job_id
                const rowError = retryError?.jobId === job.job_id ? retryError.error : null
                return (
                  <tr key={job.job_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
                    <td className="py-1.5 pr-3">
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        style={{ background: tone.bg, color: 'var(--cc-ink)' }}
                      >
                        {tone.label}
                      </span>
                    </td>
                    <td className="cc-mono py-1.5 pr-3" style={{ color: 'var(--cc-ink)' }}>
                      {job.attempts ?? 0}
                    </td>
                    <td className="py-1.5 pr-3 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                      {job.last_error ?? '—'}
                    </td>
                    <td className="py-1.5 pr-3 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                      {fmtTime(job.updated_at)}
                    </td>
                    <td className="py-1.5">
                      {job.state === 'failed' ? (
                        <>
                          <button
                            type="button"
                            aria-label={`Retry offline caption job ${job.job_id}`}
                            disabled={!canRetry || isRetrying}
                            onClick={() => onRetry(job.job_id)}
                            className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
                            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
                          >
                            {isRetrying ? 'Retrying…' : 'Retry'}
                          </button>
                          {justRetried && (
                            <span className="ml-2 text-xs" style={{ color: 'var(--cc-ok)' }}>
                              Queued for retry.
                            </span>
                          )}
                          {Boolean(rowError) && (
                            <span className="ml-2 text-xs" role="alert" style={{ color: 'var(--cc-err)' }}>
                              {apiMessage(rowError, 'Retry failed.')}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {!canRetry && rows.some((j) => j.state === 'failed') && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Retrying a failed job requires the records clerk role.
        </p>
      )}
    </section>
  )
}

export function OfflineCaptionJobsPanel({ assetId }: { assetId: string }) {
  const queryClient = useQueryClient()
  const jobsQuery = useQuery({
    queryKey: ['offline-caption-jobs', assetId],
    queryFn: () => listOfflineCaptionJobs({ assetId }),
    retry: false,
  })
  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRetry = hasRole(identityQuery.data, RETRY_ROLES)

  const [retriedJobId, setRetriedJobId] = useState<string | null>(null)
  const [retryError, setRetryError] = useState<{ jobId: string; error: unknown } | null>(null)

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retryOfflineCaptionJob(jobId),
    onSuccess: (_, jobId) => {
      setRetriedJobId(jobId)
      setRetryError(null)
      void queryClient.invalidateQueries({ queryKey: ['offline-caption-jobs', assetId] })
    },
    onError: (error, jobId) => {
      setRetryError({ jobId, error })
      setRetriedJobId(null)
    },
  })

  const handleRetry = (jobId: string) => {
    if (
      !window.confirm(
        'Retry this offline caption job? It will restart transcription from scratch with a fresh attempt budget.',
      )
    ) {
      return
    }
    retryMutation.mutate(jobId)
  }

  return (
    <OfflineCaptionJobsView
      jobs={jobsQuery.data}
      loading={jobsQuery.isLoading}
      error={jobsQuery.error}
      canRetry={canRetry}
      retryingJobId={retryMutation.isPending ? (retryMutation.variables ?? null) : null}
      retriedJobId={retriedJobId}
      retryError={retryError}
      onRetry={handleRetry}
    />
  )
}
