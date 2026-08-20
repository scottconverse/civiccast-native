import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  approveCaptionReviewItem,
  editCaptionReviewItem,
  getCaptionReviewAudioClip,
  getStaffIdentity,
  listCaptionReviewItems,
  rejectCaptionReviewItem,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import {
  CAPTION_STATUS_META,
  type CaptionReviewItemResponse,
  type CaptionReviewStatus,
} from '../types/captions'

type FilterId = 'all' | CaptionReviewStatus

const FILTERS: ReadonlyArray<{ id: FilterId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'pending', label: 'Pending' },
  { id: 'edited', label: 'Edited' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
]

const EMPTY_ITEMS: CaptionReviewItemResponse[] = []

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function fmtTime(seconds: number): string {
  const whole = Math.floor(seconds)
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function StatusPill({ status }: { status: CaptionReviewStatus }) {
  const meta = CAPTION_STATUS_META[status]
  const palette = {
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink)' },
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
    err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
  }[meta.tone]
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {meta.label}
    </span>
  )
}

function LoadingState() {
  return (
    <div className="mx-6 my-6 grid gap-3">
      {[0, 1, 2].map((item) => (
        <div
          key={item}
          className="h-24 animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const isApiError = error instanceof ApiError
  const is503 = isApiError && error.status === 503
  return (
    <div
      role="alert"
      className="mx-6 my-6 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
    >
      <div className="text-sm font-semibold">
        {is503 ? 'Caption review backend unavailable.' : 'Could not load caption review.'}
      </div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {apiMessage(error, 'The caption review request failed.')}
      </div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong>{' '}
        {is503
          ? 'Start the CivicCast server with a connected database, then retry.'
          : 'Retry this request. If it fails again, check caption review logs in deployment settings.'}
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

function EmptyState() {
  return (
    <div
      className="mx-6 my-10 rounded-md p-8 text-center"
      style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)' }}
    >
      <div className="text-sm font-semibold">No caption cues need review.</div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Stable caption cues will appear here after the captions runtime emits
        review items. Next step: run a captioned recording or live session.
      </div>
    </div>
  )
}

function PartialState({ items }: { items: CaptionReviewItemResponse[] }) {
  const count = items.filter((item) => item.low_confidence).length
  if (count === 0) return null
  return (
    <div
      className="mx-6 rounded-md p-3 text-xs"
      style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
    >
      {count} low-confidence {count === 1 ? 'cue needs' : 'cues need'} reviewer
      attention. Next step: open each flagged cue, compare against the audio,
      then approve, edit, or reject it.
    </div>
  )
}

function ReviewAudio({
  item,
  onPlayableChange,
}: {
  item: CaptionReviewItemResponse
  onPlayableChange: (playable: boolean) => void
}) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    },
    [audioUrl],
  )

  if (!item.audio_evidence_available) {
    return item.low_confidence ? (
      <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
        Audio evidence is unavailable. Approval of this low-confidence cue is
        blocked.
      </div>
    ) : null
  }

  const loadAudio = async () => {
    setLoading(true)
    setError(null)
    onPlayableChange(false)
    try {
      const blob = await getCaptionReviewAudioClip(item.review_item_id)
      const nextUrl = URL.createObjectURL(blob)
      setAudioUrl((current) => {
        if (current) URL.revokeObjectURL(current)
        return nextUrl
      })
    } catch (caught) {
      setError(apiMessage(caught, 'Could not load the retained caption audio.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid gap-2">
      {audioUrl ? (
        <audio
          controls
          preload="metadata"
          src={audioUrl}
          aria-label={`Review audio for ${item.review_item_id}`}
          onCanPlay={() => onPlayableChange(true)}
          onError={() => {
            onPlayableChange(false)
            setError('The retained caption audio could not be played.')
          }}
        />
      ) : (
        <button
          type="button"
          onClick={loadAudio}
          disabled={loading}
          className="w-fit rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: 'var(--cc-surface-2)',
            border: '1px solid var(--cc-line-strong)',
            color: 'var(--cc-ink)',
          }}
        >
          {loading ? 'Loading review audio…' : 'Load review audio'}
        </button>
      )}
      {error && (
        <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
          {error}
        </div>
      )}
    </div>
  )
}

export function ReviewCard({
  item,
  busy,
  onApprove,
  onEdit,
  onReject,
  canReview,
}: {
  item: CaptionReviewItemResponse
  busy: boolean
  onApprove: (
    item: CaptionReviewItemResponse,
    lowConfidenceAcknowledged: boolean,
  ) => void
  onEdit: (item: CaptionReviewItemResponse, text: string) => void
  onReject: (item: CaptionReviewItemResponse) => void
  canReview: boolean
}) {
  const [draft, setDraft] = useState(item.reviewed_text ?? item.original_text)
  const [lowConfidenceAcknowledged, setLowConfidenceAcknowledged] =
    useState(false)
  const evidenceKey = `${item.review_item_id}:${item.updated_at}:${item.audio_evidence_available}`
  const [playableEvidenceKey, setPlayableEvidenceKey] = useState<string | null>(
    null,
  )
  const audioEvidencePlayable =
    item.audio_evidence_available && playableEvidenceKey === evidenceKey
  const dirty = draft.trim() !== (item.reviewed_text ?? item.original_text)
  return (
    <article
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">{item.asset_id}</div>
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {item.review_item_id} / {fmtTime(item.cue.start_seconds)}-{fmtTime(item.cue.end_seconds)}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {item.low_confidence && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
            >
              Low confidence
            </span>
          )}
          <StatusPill status={item.status} />
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <div>
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Machine cue
          </div>
          <p className="m-0 mt-1 rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
            {item.original_text}
          </p>
        </div>
        <label className="block">
          <span className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Reviewed text
          </span>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={!canReview}
            className="mt-1 min-h-20 w-full rounded-md p-3 text-sm"
            style={{
              background: 'var(--cc-paper)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
            aria-label={`Reviewed text for ${item.review_item_id}`}
          />
        </label>
      </div>

      {item.reviewer_note && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Last note: {item.reviewer_note}
        </div>
      )}

      <ReviewAudio
        key={evidenceKey}
        item={item}
        onPlayableChange={(playable) =>
          setPlayableEvidenceKey(playable ? evidenceKey : null)
        }
      />

      {item.low_confidence && (
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={lowConfidenceAcknowledged}
            onChange={(event) =>
              setLowConfidenceAcknowledged(event.target.checked)
            }
            disabled={!canReview || busy || !audioEvidencePlayable}
            aria-label={`I compared ${item.review_item_id} with its audio evidence`}
          />
          <span>
            I compared this low-confidence cue with its audio evidence.
          </span>
        </label>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() =>
            onApprove(
              item,
              item.low_confidence ? lowConfidenceAcknowledged : false,
            )
          }
          disabled={
            !canReview ||
            busy ||
            (item.low_confidence &&
              (!audioEvidencePlayable || !lowConfidenceAcknowledged))
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: 'var(--cc-ok-soft)',
            border: '1px solid var(--cc-line-strong)',
            color: 'var(--cc-ink)',
          }}
        >
          Approve
        </button>
        <button
          type="button"
          onClick={() => onEdit(item, draft)}
          disabled={!canReview || busy || !dirty || draft.trim().length === 0}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: canReview && dirty ? 'var(--cc-brand)' : 'var(--cc-surface-3)',
            color: canReview && dirty ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)',
          }}
        >
          Save edit
        </button>
        <button
          type="button"
          onClick={() => onReject(item)}
          disabled={!canReview || busy}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: 'var(--cc-err-soft)',
            border: '1px solid var(--cc-line-strong)',
            color: 'var(--cc-ink)',
          }}
        >
          Reject
        </button>
      </div>
    </article>
  )
}

export function ReviewQueueScreen() {
  const [filter, setFilter] = useState<FilterId>('pending')
  const [search, setSearch] = useState('')
  const [approvalFailureGenerations, setApprovalFailureGenerations] = useState<
    Record<string, number>
  >({})
  const queryClient = useQueryClient()

  const query = useQuery<CaptionReviewItemResponse[], Error>({
    queryKey: ['caption-review-items'],
    queryFn: () => listCaptionReviewItems(),
    retry: false,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canReview = !staffIdentityQuery.isSuccess || hasOperatorRole(staffIdentityQuery.data, 'records_clerk')

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['caption-review-items'] })

  const approveMutation = useMutation({
    mutationFn: ({
      item,
      lowConfidenceAcknowledged,
    }: {
      item: CaptionReviewItemResponse
      lowConfidenceAcknowledged: boolean
    }) =>
      approveCaptionReviewItem(item.review_item_id, {
        reviewer_note: lowConfidenceAcknowledged
          ? 'Approved in operator console after audio comparison.'
          : 'Approved in operator console.',
        low_confidence_acknowledged: lowConfidenceAcknowledged,
      }),
    onSuccess: invalidate,
  })
  const editMutation = useMutation({
    mutationFn: ({ item, text }: { item: CaptionReviewItemResponse; text: string }) =>
      editCaptionReviewItem(item.review_item_id, {
        text,
        reviewer_note: 'Edited in operator console.',
      }),
    onSuccess: invalidate,
  })
  const rejectMutation = useMutation({
    mutationFn: (item: CaptionReviewItemResponse) =>
      rejectCaptionReviewItem(item.review_item_id, { reviewer_note: 'Rejected in operator console.' }),
    onSuccess: invalidate,
  })

  const items = query.data ?? EMPTY_ITEMS
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return items.filter((item) => {
      if (filter !== 'all' && item.status !== filter) return false
      if (
        needle &&
        !item.asset_id.toLowerCase().includes(needle) &&
        !item.original_text.toLowerCase().includes(needle) &&
        !(item.reviewed_text ?? '').toLowerCase().includes(needle)
      ) {
        return false
      }
      return true
    })
  }, [filter, items, search])

  const busy =
    approveMutation.isPending || editMutation.isPending || rejectMutation.isPending
  const mutationError =
    approveMutation.error ?? editMutation.error ?? rejectMutation.error

  return (
    <div className="flex flex-col gap-4">
      <header className="px-6 pb-2 pt-6">
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Caption review
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Review queue</h1>
        <p className="m-0 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Review low-confidence captions, preserve the machine cue, and approve
          the text that should become part of the public record.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3 px-6">
        <label
          className="cc-search-shell flex min-w-60 flex-1 items-center gap-2 rounded-md px-3 py-1.5"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          <span aria-hidden="true" className="text-xs font-semibold" style={{ color: 'var(--cc-ink-3)' }}>
            Search
          </span>
          <input
            aria-label="Search caption review"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search asset or caption text..."
            className="w-full bg-transparent text-sm outline-none"
            style={{ color: 'var(--cc-ink)' }}
          />
        </label>
        <div role="tablist" aria-label="Caption review filter" className="flex flex-wrap gap-2">
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

      {staffIdentityQuery.isSuccess && !canReview && (
        <div className="mx-6 rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          Caption review actions require the records clerk role. The queue stays visible for read-only review.
        </div>
      )}

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {mutationError && (
        <ErrorState
          error={mutationError}
          onRetry={() => {
            approveMutation.reset()
            editMutation.reset()
            rejectMutation.reset()
          }}
        />
      )}
      {query.isSuccess && <PartialState items={items} />}
      {query.isSuccess && items.length === 0 && <EmptyState />}
      {query.isSuccess && items.length > 0 && visible.length === 0 && (
        <div
          className="mx-6 rounded-md p-4 text-center text-xs"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
        >
          No captions match the current search and filter.
        </div>
      )}
      {query.isSuccess && visible.length > 0 && (
        <div className="grid gap-3 px-6 pb-6">
          {visible.map((item) => (
            <ReviewCard
              key={`${item.review_item_id}:${approvalFailureGenerations[item.review_item_id] ?? 0}`}
              item={item}
              busy={busy}
              onApprove={(target, lowConfidenceAcknowledged) =>
                approveMutation.mutate(
                  {
                    item: target,
                    lowConfidenceAcknowledged,
                  },
                  {
                    onError: () =>
                      setApprovalFailureGenerations((generations) => ({
                        ...generations,
                        [target.review_item_id]:
                          (generations[target.review_item_id] ?? 0) + 1,
                      })),
                  },
                )
              }
              onEdit={(target, text) => editMutation.mutate({ item: target, text })}
              onReject={(target) => rejectMutation.mutate(target)}
              canReview={canReview}
            />
          ))}
        </div>
      )}
    </div>
  )
}
