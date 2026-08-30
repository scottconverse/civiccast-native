import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  ApiError,
  createSummaryJob,
  getStaffIdentity,
  listCaptionReviewItems,
  listSummaryJobs,
  retrySummaryJob,
} from '../api/client'
import type { CaptionCue, SummaryGenerationJobRecord } from '../types/api.generated'
import { hasRole } from './contribution-format'

// records_clerk or support_admin can queue a job (mirrors the /generate role gate);
// retry is records_clerk-only (mirrors captions.router.retry_offline_caption_job).
const GENERATE_ROLES = ['records_clerk', 'support_admin']
const RETRY_ROLES = ['records_clerk']

// Field evidence 2026-08-29 (candidate #17, 32GB CPU-only reference station):
// gemma4:e4b (the CPU-only default) completed in 94-128s; 12B took up to 366s or
// failed outright. This is an honest range, not a promise -- CPU inference time
// varies with meeting length and station load.
const EXPECTED_DURATION_NOTE =
  'Generating locally can take 1-6 minutes on a CPU-only station, depending on ' +
  'meeting length and what else is running. This tab can be closed and reopened ' +
  '— the job keeps running and this panel picks the status back up.'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function isActive(job: SummaryGenerationJobRecord | undefined): boolean {
  return job?.state === 'pending' || job?.state === 'running'
}

/** Presentational only (no data fetching, no mutation) so the row states --
 *  no-cues / idle / running / complete / failed -- unit-test without a network. */
export function GenerateSummaryView({
  committedCueCount,
  latestJob,
  canGenerate,
  canRetry,
  generating,
  retrying,
  generateError,
  retryError,
  onGenerate,
  onRetry,
}: {
  committedCueCount: number
  latestJob: SummaryGenerationJobRecord | undefined
  canGenerate: boolean
  canRetry: boolean
  generating: boolean
  retrying: boolean
  generateError?: unknown
  retryError?: unknown
  onGenerate: () => void
  onRetry: (jobId: string) => void
}) {
  const active = isActive(latestJob)
  const noCuesYet = committedCueCount === 0

  return (
    <section
      aria-label="Generate summary"
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">AI summary</h2>
        {active && (
          <span
            className="cc-mono rounded-full px-2 py-1 text-[11px]"
            style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
          >
            {latestJob?.state === 'running' ? 'generating…' : 'queued'}
          </span>
        )}
        {latestJob?.state === 'complete' && (
          <span
            className="cc-mono rounded-full px-2 py-1 text-[11px]"
            style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}
          >
            done
          </span>
        )}
        {latestJob?.state === 'failed' && (
          <span
            className="cc-mono rounded-full px-2 py-1 text-[11px]"
            style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
          >
            failed
          </span>
        )}
      </div>

      {noCuesYet && !latestJob && (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          No committed transcript cues yet. Approve caption review items for this
          recording first, then a summary can be generated from them.
        </p>
      )}

      {!noCuesYet && !latestJob && (
        <>
          <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Generate a sourced summary from the {committedCueCount} committed
            transcript {committedCueCount === 1 ? 'cue' : 'cues'} on this recording.
          </p>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {EXPECTED_DURATION_NOTE}
          </p>
          {Boolean(generateError) && (
            <div
              role="alert"
              className="rounded-md p-2 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              {apiMessage(generateError, 'Could not queue summary generation.')}
            </div>
          )}
          <button
            type="button"
            disabled={!canGenerate || generating}
            onClick={onGenerate}
            className="w-fit rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {generating ? 'Queuing…' : 'Generate summary'}
          </button>
          {!canGenerate && (
            <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Generating a summary requires the records clerk or support admin role.
            </p>
          )}
        </>
      )}

      {active && (
        <>
          <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            {latestJob?.state === 'running'
              ? 'The local model is generating this summary now.'
              : 'Queued; a worker will pick this up shortly.'}
          </p>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {EXPECTED_DURATION_NOTE}
          </p>
          {latestJob && (latestJob.attempts ?? 0) > 0 && (
            <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Attempt {(latestJob.attempts ?? 0) + 1}
              {latestJob.last_error ? ` — previous attempt: ${latestJob.last_error}` : ''}
            </p>
          )}
        </>
      )}

      {latestJob?.state === 'complete' && (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Summary generated.{' '}
          <Link to="/summary" className="underline">
            Review it in Summary review
          </Link>
          .
        </p>
      )}

      {latestJob?.state === 'failed' && (
        <>
          <div
            role="alert"
            className="rounded-md p-2 text-xs"
            style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
          >
            Summary generation failed after {latestJob.attempts}{' '}
            {latestJob.attempts === 1 ? 'attempt' : 'attempts'}:{' '}
            {latestJob.last_error || 'no error detail was recorded.'}
          </div>
          {Boolean(retryError) && (
            <div
              role="alert"
              className="rounded-md p-2 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              {apiMessage(retryError, 'Retry failed.')}
            </div>
          )}
          <button
            type="button"
            disabled={!canRetry || retrying}
            onClick={() => onRetry(latestJob.job_id)}
            className="w-fit rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {retrying ? 'Retrying…' : 'Retry'}
          </button>
          {!canRetry && (
            <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Retrying requires the records clerk role.
            </p>
          )}
        </>
      )}
    </section>
  )
}

export function GenerateSummaryPanel({ assetId }: { assetId: string }) {
  const queryClient = useQueryClient()

  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canGenerate = hasRole(identityQuery.data, GENERATE_ROLES)
  const canRetry = hasRole(identityQuery.data, RETRY_ROLES)

  const committedCuesQuery = useQuery({
    queryKey: ['caption-review-items', assetId, 'approved'],
    queryFn: () => listCaptionReviewItems({ asset_id: assetId, status_filter: 'approved' }),
    retry: false,
  })
  const committedCues = useMemo<CaptionCue[]>(
    () =>
      (committedCuesQuery.data ?? []).map((item) => ({
        ...item.cue,
        // An operator's edited text (caption review) is the accurate transcript;
        // the summary should cite what was actually approved, not the raw model
        // hypothesis it started from.
        text: item.reviewed_text ?? item.cue.text,
      })),
    [committedCuesQuery.data],
  )

  const jobsQuery = useQuery({
    queryKey: ['summary-jobs', assetId],
    queryFn: () => listSummaryJobs({ meetingId: assetId }),
    retry: false,
    // Poll while a job is in flight so the operator sees real progress
    // (pending -> running -> complete/failed) without refreshing the page.
    refetchInterval: (query) => {
      const rows = query.state.data
      const latest = rows?.[rows.length - 1]
      return isActive(latest) ? 5000 : false
    },
  })
  const latestJob = jobsQuery.data?.[jobsQuery.data.length - 1]

  const generateMutation = useMutation({
    mutationFn: () => createSummaryJob({ meeting_id: assetId, cues: committedCues }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['summary-jobs', assetId] })
    },
  })

  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retrySummaryJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['summary-jobs', assetId] })
    },
  })

  return (
    <GenerateSummaryView
      committedCueCount={committedCues.length}
      latestJob={latestJob}
      canGenerate={canGenerate}
      canRetry={canRetry}
      generating={generateMutation.isPending}
      retrying={retryMutation.isPending}
      generateError={generateMutation.error}
      retryError={retryMutation.error}
      onGenerate={() => generateMutation.mutate()}
      onRetry={(jobId) => retryMutation.mutate(jobId)}
    />
  )
}
