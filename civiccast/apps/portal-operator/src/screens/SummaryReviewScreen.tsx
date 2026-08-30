import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, approveSummary, exportSignedRecord, getStaffIdentity, listSummaryReviewItems } from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { SourcedClaimList } from '../components/review/SourcedClaimList'
import { TranscriptCuePlayer } from '../components/review/TranscriptCuePlayer'
import type { RecordExportResponse, SummaryDraft, TranscriptRange } from '../types/api.generated'
import { SUMMARY_STATUS_META } from '../types/summary'

const OPERATOR = {
  operator_id: 'operator-console',
  operator_display_name: 'Operator console',
  approval_note: 'Approved after checking sourced-claim transcript links.',
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function StatusPill({ status }: { status: SummaryDraft['status'] }) {
  const meta = SUMMARY_STATUS_META[status]
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
      {[0, 1].map((item) => (
        <div
          key={item}
          className="h-36 animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="mx-6 my-6 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
    >
      <div className="text-sm font-semibold">Could not load summary review.</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {apiMessage(error, 'The summary review request failed.')}
      </div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong> Retry this request. If it fails again, check
        summary review logs and confirm the CivicCast database is connected.
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
      <div className="text-sm font-semibold">No summaries need review.</div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Next step: open a recording's asset detail page and use the "Generate
        summary" action there (next to its offline caption jobs) to start one
        from its committed transcript cues. New pending summaries and evidence
        refusals will appear here once generation completes.
      </div>
    </div>
  )
}

function PartialState({ summaries }: { summaries: SummaryDraft[] }) {
  const refused = summaries.filter((summary) => summary.status === 'refused').length
  const unsourced = summaries.filter((summary) => (summary.sourced_claims ?? []).length === 0).length
  if (refused === 0 && unsourced === 0) return null
  return (
    <div
      className="mx-6 rounded-md p-3 text-xs"
      style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
    >
      {refused + unsourced} summary {refused + unsourced === 1 ? 'needs' : 'items need'} more
      evidence before export. Next step: regenerate from committed transcript cues or
      add timestamp-backed source ranges before approving.
    </div>
  )
}

function SummaryCard({
  summary,
  activeCueId,
  exportResult,
  busy,
  onSeek,
  onApprove,
  onExport,
  canReview,
}: {
  summary: SummaryDraft
  activeCueId: string | null
  exportResult: RecordExportResponse | null
  busy: boolean
  onSeek: (cueId: string) => void
  onApprove: (summary: SummaryDraft) => void
  onExport: (summary: SummaryDraft) => void
  canReview: boolean
}) {
  const ranges = useMemo<TranscriptRange[]>(
    () => (summary.sourced_claims ?? []).flatMap((claim) => claim.transcript_ranges ?? []),
    [summary.sourced_claims],
  )
  const canApprove = summary.status === 'pending_review' && (summary.sourced_claims ?? []).length > 0
  const canExport = summary.status === 'approved'
  return (
    <article
      className="grid gap-4 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">{summary.meeting_id}</div>
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {summary.summary_id} / {summary.provenance.model_tag}
          </div>
        </div>
        <StatusPill status={summary.status} />
      </div>

      {summary.operator_message && (
        <div
          className="rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
        >
          {summary.operator_message} Next step: regenerate after adding transcript evidence
          for each quantitative claim.
        </div>
      )}

      <p className="m-0 rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
        {summary.narrative}
      </p>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SourcedClaimList claims={summary.sourced_claims ?? []} onSeek={onSeek} />
        <TranscriptCuePlayer ranges={ranges} activeCueId={activeCueId} />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onApprove(summary)}
          disabled={!canReview || busy || !canApprove}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: canReview && canApprove ? 'var(--cc-ok-soft)' : 'var(--cc-surface-3)',
            border: '1px solid var(--cc-line-strong)',
            color: canReview && canApprove ? 'var(--cc-ink)' : 'var(--cc-ink-3)',
          }}
        >
          Approve summary
        </button>
        <button
          type="button"
          onClick={() => onExport(summary)}
          disabled={!canReview || busy || !canExport}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: canReview && canExport ? 'var(--cc-brand)' : 'var(--cc-surface-3)',
            color: canReview && canExport ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)',
          }}
        >
          Export signed record
        </button>
      </div>

      {exportResult && exportResult.summary_id === summary.summary_id && (
        <div
          className="rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}
        >
          Signed record exported: {exportResult.record_id}. Digest{' '}
          {exportResult.timestamp_proof.artifact_digest}. The server validates the
          PDF/A-3B artifact; timestamp authority remains deterministic unless a
          real authority is configured.
        </div>
      )}
    </article>
  )
}

export function SummaryReviewScreen() {
  const [activeCueId, setActiveCueId] = useState<string | null>(null)
  const [exportResult, setExportResult] = useState<RecordExportResponse | null>(null)
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['summary-review-items'],
    queryFn: () => listSummaryReviewItems(),
    retry: false,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canReview = !staffIdentityQuery.isSuccess || hasOperatorRole(staffIdentityQuery.data, 'records_clerk')

  const approveMutation = useMutation({
    mutationFn: (summary: SummaryDraft) => approveSummary(summary.summary_id, OPERATOR),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['summary-review-items'] }),
  })

  const exportMutation = useMutation({
    mutationFn: (summary: SummaryDraft) =>
      exportSignedRecord({
        summary_id: summary.summary_id,
        summary_status: summary.status,
      }),
    onSuccess: (record) => setExportResult(record),
  })

  const summaries = query.data?.items ?? []
  const busy = approveMutation.isPending || exportMutation.isPending
  const mutationError = approveMutation.error ?? exportMutation.error

  return (
    <div className="flex flex-col gap-4">
      <header className="px-6 pb-2 pt-6">
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Summary + signed records
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Summary review</h1>
        <p className="m-0 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Approve only summaries whose quantitative claims link to transcript cue
          timestamps, then export the PDF/A-3B signed-record artifact for local
          record review.
        </p>
      </header>

      {staffIdentityQuery.isSuccess && !canReview && (
        <div className="mx-6 rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          Summary approval and signed-record export require the records clerk role. Evidence remains readable.
        </div>
      )}

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {mutationError && (
        <ErrorState
          error={mutationError}
          onRetry={() => {
            approveMutation.reset()
            exportMutation.reset()
          }}
        />
      )}
      {query.isSuccess && <PartialState summaries={summaries} />}
      {query.isSuccess && summaries.length === 0 && <EmptyState />}
      {query.isSuccess && summaries.length > 0 && (
        <div className="grid gap-3 px-6 pb-6">
          {summaries.map((summary) => (
            <SummaryCard
              key={summary.summary_id}
              summary={summary}
              activeCueId={activeCueId}
              exportResult={exportResult}
              busy={busy}
              onSeek={setActiveCueId}
              onApprove={(target) => approveMutation.mutate(target)}
              onExport={(target) => exportMutation.mutate(target)}
              canReview={canReview}
            />
          ))}
        </div>
      )}
    </div>
  )
}
