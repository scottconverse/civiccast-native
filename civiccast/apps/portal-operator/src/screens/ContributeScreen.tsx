import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  getContributorNotificationOutbox,
  getProducerActivityReport,
  listContributorSubmissions,
  reviewContributorSubmission,
} from '../api/client'
import type {
  ContributorSubmission,
  ProducerActivityReportRow,
  SubmissionStatusNotification,
} from '../types/api.generated'

type ContributorSubmissionState = ContributorSubmission['state']
type FilterId = 'all' | ContributorSubmissionState
type ReviewAction = 'mark_under_review' | 'request_changes' | 'accept' | 'decline' | 'schedule'

interface ReviewIntent {
  item: ContributorSubmission
  action: ReviewAction
  metadataPatch?: {
    title?: string
    description?: string
    tags?: string[]
    producer_name?: string
  }
  declineReason?: string
  operatorNotes?: string
  durationSeconds?: number
}

const FILTERS: ReadonlyArray<{ id: FilterId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'submitted', label: 'Submitted' },
  { id: 'under_review', label: 'Reviewing' },
  { id: 'needs_changes', label: 'Needs changes' },
  { id: 'accepted', label: 'Accepted' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'declined', label: 'Declined' },
]
const EMPTY_SUBMISSIONS: ContributorSubmission[] = []

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

// `Intl.DateTimeFormat.format()` THROWS RangeError on an Invalid Date, the
// same as `toISOString()`. The falsy check alone was not enough: this renders
// `requested_air_date`, which a member of the public types into the
// contributor submission form, so a value the browser cannot parse is an
// ordinary occurrence rather than an edge case. Unguarded, one such
// submission blanked the whole contributions list during render.
function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not requested'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return 'Unreadable date'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}

function statusTone(state: ContributorSubmissionState): { bg: string; fg: string } {
  if (state === 'declined') return { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' }
  if (state === 'accepted' || state === 'scheduled' || state === 'published') {
    return { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' }
  }
  if (state === 'needs_changes') return { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' }
  return { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink)' }
}

function StatusPill({ state }: { state: ContributorSubmissionState }) {
  const tone = statusTone(state)
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {state.replace('_', ' ')}
    </span>
  )
}

function ErrorBox({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mx-6 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
    >
      <div className="font-semibold">Contributor queue could not load.</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {apiMessage(error, 'The contributor workflow request failed.')}
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-md px-3 py-1.5 text-xs font-medium"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        Retry
      </button>
    </div>
  )
}

function ProducerReport({ rows }: { rows: ProducerActivityReportRow[] }) {
  if (rows.length === 0) return null
  return (
    <section
      className="mx-6 grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      aria-labelledby="producer-report-heading"
    >
      <h2 id="producer-report-heading" className="m-0 text-sm font-semibold">
        Producer activity
      </h2>
      <div className="grid gap-2 md:grid-cols-3">
        {rows.map((row) => (
          <div
            key={row.contributor_id}
            className="rounded-md p-3"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <div className="text-sm font-semibold">{row.producer_name}</div>
            <div className="cc-mono mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              {row.submitted_count} submitted / {row.scheduled_count} scheduled /{' '}
              {row.declined_count} declined
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function NotificationOutbox({ notifications }: { notifications: SubmissionStatusNotification[] }) {
  if (notifications.length === 0) return null
  return (
    <section
      className="mx-6 grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      aria-labelledby="notification-outbox-heading"
    >
      <h2 id="notification-outbox-heading" className="m-0 text-sm font-semibold">
        Status notification outbox
      </h2>
      <div className="grid gap-2 md:grid-cols-2">
        {notifications.slice(-6).map((notice) => (
          <div
            key={`${notice.target}-${notice.state}-${notice.queued_at}`}
            className="rounded-md p-3"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-semibold">{notice.kind}</span>
              <span className="cc-mono" style={{ color: 'var(--cc-ink-3)' }}>
                {formatDate(notice.queued_at)}
              </span>
            </div>
            <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              {notice.target} / {notice.state.replace('_', ' ')}
            </div>
            <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              {notice.message}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function SubmissionCard({
  item,
  busy,
  onReview,
}: {
  item: ContributorSubmission
  busy: boolean
  onReview: (intent: ReviewIntent) => void
}) {
  const [title, setTitle] = useState(item.title)
  const [description, setDescription] = useState(item.description)
  const [tags, setTags] = useState(item.tags.join(', '))
  const [declineReason, setDeclineReason] = useState(item.decline_reason ?? '')
  const [operatorNotes, setOperatorNotes] = useState(item.operator_notes ?? '')
  const [durationMinutes, setDurationMinutes] = useState('30')
  const metadataPatch = {
    title,
    description,
    tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean),
    producer_name: item.producer_name,
  }
  return (
    <article
      className="grid gap-4 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">{item.title}</div>
          <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            {item.producer_name} / {item.contributor.organization ?? item.contributor.display_name}
          </div>
          <div className="cc-mono mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {item.submission_id} / requested {formatDate(item.requested_air_date)}
          </div>
        </div>
        <StatusPill state={item.state} />
      </div>

      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        {item.description}
      </p>

      <div className="grid gap-2 text-xs md:grid-cols-3">
        <div>
          <div className="font-semibold">Media</div>
          <div style={{ color: 'var(--cc-ink-3)' }}>
            {item.media.filename} / {Math.ceil(item.media.size_bytes / 1024)} KB
          </div>
        </div>
        <div>
          <div className="font-semibold">Media gate</div>
          <div style={{ color: 'var(--cc-ink-3)' }}>
            {(item.broken_media_gate?.state ?? 'not_run').replace('_', ' ')}
          </div>
        </div>
        <div>
          <div className="font-semibold">Agreement</div>
          <div style={{ color: 'var(--cc-ink-3)' }}>
            {item.agreements[0]?.agreement_id ?? 'missing'} / {item.agreements[0]?.version ?? '-'}
          </div>
        </div>
      </div>

      {item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {item.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full px-2 py-0.5 text-[10px]"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Review title</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.currentTarget.value)}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Review tags</span>
          <input
            value={tags}
            onChange={(event) => setTags(event.currentTarget.value)}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
        <label className="grid gap-1 text-xs md:col-span-2">
          <span className="font-semibold">Review description</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
            className="min-h-20 rounded-md px-3 py-2"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Operator note or change request</span>
          <input
            value={operatorNotes}
            onChange={(event) => setOperatorNotes(event.currentTarget.value)}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Decline reason</span>
          <input
            value={declineReason}
            onChange={(event) => setDeclineReason(event.currentTarget.value)}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
      </div>

      {item.decline_reason && (
        <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)' }}>
          Decline reason: {item.decline_reason}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || item.state !== 'submitted'}
          onClick={() => onReview({ item, action: 'mark_under_review', operatorNotes })}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          Start review
        </button>
        <button
          type="button"
          disabled={busy || !['submitted', 'under_review', 'needs_changes'].includes(item.state)}
          onClick={() =>
            onReview({
              item,
              action: 'request_changes',
              metadataPatch,
              operatorNotes: operatorNotes || 'Changes requested from operator review queue.',
            })
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-line)' }}
        >
          Request changes
        </button>
        <button
          type="button"
          disabled={busy || !['submitted', 'under_review', 'needs_changes'].includes(item.state)}
          onClick={() => onReview({ item, action: 'accept', metadataPatch, operatorNotes })}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-ok-soft)', border: '1px solid var(--cc-line)' }}
        >
          Accept
        </button>
        <button
          type="button"
          disabled={busy || item.state !== 'accepted'}
          onClick={() =>
            onReview({
              item,
              action: 'schedule',
              durationSeconds: Math.max(60, Number(durationMinutes) * 60 || 1800),
            })
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          Send to schedule
        </button>
        <label className="flex items-center gap-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          <span>Minutes</span>
          <input
            value={durationMinutes}
            onChange={(event) => setDurationMinutes(event.currentTarget.value)}
            className="w-16 rounded-md px-2 py-1"
            inputMode="numeric"
            style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
          />
        </label>
        <button
          type="button"
          disabled={busy || ['declined', 'scheduled', 'published'].includes(item.state)}
          onClick={() =>
            onReview({
              item,
              action: 'decline',
              declineReason: declineReason || 'Declined from operator review queue.',
              operatorNotes,
            })
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-line)' }}
        >
          Decline
        </button>
      </div>
    </article>
  )
}

export function ContributeScreen() {
  const [filter, setFilter] = useState<FilterId>('all')
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()
  const queueQuery = useQuery({
    queryKey: ['contributor-submissions'],
    queryFn: listContributorSubmissions,
    retry: false,
  })
  const reportQuery = useQuery({
    queryKey: ['producer-report'],
    queryFn: getProducerActivityReport,
    retry: false,
  })
  const outboxQuery = useQuery({
    queryKey: ['contributor-notification-outbox'],
    queryFn: getContributorNotificationOutbox,
    retry: false,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['contributor-submissions'] })
    void queryClient.invalidateQueries({ queryKey: ['producer-report'] })
    void queryClient.invalidateQueries({ queryKey: ['contributor-notification-outbox'] })
  }

  const reviewMutation = useMutation({
    mutationFn: ({
      item,
      action,
      metadataPatch,
      declineReason,
      operatorNotes,
      durationSeconds,
    }: ReviewIntent) => {
      if (action === 'decline') {
        return reviewContributorSubmission(item.submission_id, {
          action,
          decline_reason: declineReason ?? 'Declined from operator review queue.',
          operator_notes: operatorNotes || undefined,
        })
      }
      if (action === 'accept') {
        // The station's ffprobe probe runs automatically on the server when
        // this is sent -- it reads the contributor's actual file and decides
        // pass/fail itself, so the client no longer sends a canned "passed"
        // attestation the server would have to either trust blindly or
        // silently discard. A corrupt/unsupported file is rejected here with
        // a real error instead of being accepted on a fabricated claim.
        return reviewContributorSubmission(item.submission_id, {
          action,
          metadata_patch: metadataPatch,
          operator_notes: operatorNotes || undefined,
        })
      }
      if (action === 'schedule') {
        return reviewContributorSubmission(item.submission_id, {
          action,
          schedule_handoff: {
            channel_id: item.channel_id,
            requested_start: item.requested_air_date ?? new Date().toISOString(),
            duration_seconds: durationSeconds ?? 1800,
            notes: 'Created from contributor review queue.',
          },
        })
      }
      return reviewContributorSubmission(item.submission_id, {
        action,
        metadata_patch: metadataPatch,
        operator_notes: operatorNotes || `${action.replace('_', ' ')} from operator review queue.`,
      })
    },
    onSuccess: invalidate,
  })

  const submissions = queueQuery.data?.submissions ?? EMPTY_SUBMISSIONS
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return submissions.filter((item) => {
      if (filter !== 'all' && item.state !== filter) return false
      if (
        needle &&
        !item.title.toLowerCase().includes(needle) &&
        !item.producer_name.toLowerCase().includes(needle) &&
        !item.tags.some((tag) => tag.toLowerCase().includes(needle))
      ) {
        return false
      }
      return true
    })
  }, [filter, search, submissions])

  return (
    <div className="flex flex-col gap-4">
      <header className="px-6 pb-2 pt-6">
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Producer workflow
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Contributor submissions</h1>
        <p className="m-0 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Review programs from external producers, keep the broken-media gate visible,
          and hand accepted content to scheduling without giving contributors operator access.
        </p>
      </header>

      <div className="grid gap-3 px-6 md:grid-cols-3">
        <Metric label="Needs action" value={queueQuery.data?.needs_operator_action ?? 0} />
        <Metric label="Total submissions" value={submissions.length} />
        <Metric label="Status notices" value={outboxQuery.data?.notifications.length ?? 0} />
      </div>

      <div className="flex flex-wrap items-center gap-3 px-6">
        <label
          className="flex min-w-60 flex-1 items-center gap-2 rounded-md px-3 py-1.5"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          <span className="text-xs font-semibold" style={{ color: 'var(--cc-ink-3)' }}>
            Search
          </span>
          <input
            aria-label="Search contributor submissions"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search title, producer, or tag..."
            className="w-full bg-transparent text-sm outline-none"
            style={{ color: 'var(--cc-ink)' }}
          />
        </label>
        <div role="tablist" aria-label="Contributor submission filter" className="flex flex-wrap gap-2">
          {FILTERS.map((item) => {
            const active = item.id === filter
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(item.id)}
                className="min-h-8 rounded-md px-3 py-2 text-xs font-medium"
                style={{
                  background: active ? 'var(--cc-ink)' : 'transparent',
                  color: active ? 'var(--cc-ink-inv)' : 'var(--cc-ink-2)',
                  border: '1px solid transparent',
                }}
              >
                {item.label}
              </button>
            )
          })}
        </div>
      </div>

      {queueQuery.isLoading && (
        <div className="mx-6 h-24 animate-pulse rounded-md" style={{ background: 'var(--cc-surface-2)' }} />
      )}
      {queueQuery.isError && <ErrorBox error={queueQuery.error} onRetry={() => queueQuery.refetch()} />}
      {reviewMutation.error && (
        <ErrorBox
          error={reviewMutation.error}
          onRetry={() => reviewMutation.reset()}
        />
      )}
      {queueQuery.isSuccess && submissions.length === 0 && (
        <div
          className="mx-6 rounded-md p-8 text-center text-sm"
          style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)' }}
        >
          No contributor submissions are waiting.
        </div>
      )}
      {queueQuery.isSuccess && submissions.length > 0 && visible.length === 0 && (
        <div
          className="mx-6 rounded-md p-4 text-center text-xs"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
        >
          No contributor submissions match the current filter.
        </div>
      )}
      {visible.length > 0 && (
        <div className="grid gap-3 px-6">
          {visible.map((item) => (
            <SubmissionCard
              key={item.submission_id}
              item={item}
              busy={reviewMutation.isPending}
              onReview={(intent) => reviewMutation.mutate(intent)}
            />
          ))}
        </div>
      )}
      <ProducerReport rows={reportQuery.data?.rows ?? []} />
      <NotificationOutbox notifications={outboxQuery.data?.notifications ?? []} />
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="cc-mono text-2xl font-semibold">{value}</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        {label}
      </div>
    </div>
  )
}
