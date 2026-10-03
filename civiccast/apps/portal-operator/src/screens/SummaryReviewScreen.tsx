import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, approveSummary, downloadSignedRecord, exportSignedRecord, getStaffIdentity, listSummaryReviewItems, verifySignedRecord } from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { SourcedClaimList } from '../components/review/SourcedClaimList'
import { TranscriptCuePlayer } from '../components/review/TranscriptCuePlayer'
import type { RecordExportResponse, SummaryApprovalRequest, SummaryDraft, TranscriptRange } from '../types/api.generated'
import { SUMMARY_STATUS_META } from '../types/summary'

const APPROVAL_PAYLOAD = {
  approval_note: 'Approved after checking sourced-claim transcript links.',
} satisfies SummaryApprovalRequest

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

function ErrorState({ error, onRetry, title = 'Could not load summary review.', canRetry = true }: { error: Error; onRetry: () => void; title?: string; canRetry?: boolean }) {
  return (
    <div
      role="alert"
      className="mx-6 my-6 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
    >
      <div className="text-sm font-semibold">{title}</div>
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
        disabled={!canRetry}
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
  const incomplete = summaries.filter((summary) => summary.status === 'refused' || (summary.sourced_claims ?? []).length === 0 || (summary.sourced_claims ?? []).some((claim) => (claim.transcript_ranges ?? []).length === 0)).length
  if (incomplete === 0) return null
  return (
    <div
      className="mx-6 rounded-md p-3 text-xs"
      style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
    >
      {incomplete} summary {incomplete === 1 ? 'needs' : 'items need'} more
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
  onDownload,
  onVerify,
  canReview,
  approvalRequired,
}: {
  summary: SummaryDraft
  activeCueId: string | null
  exportResult: RecordExportResponse | null
  busy: boolean
  onSeek: (cueId: string) => void
  onApprove: (summary: SummaryDraft) => void
  onExport: (summary: SummaryDraft) => void
  onDownload: (record: RecordExportResponse) => void
  onVerify: (record: RecordExportResponse) => void
  canReview: boolean
  approvalRequired: boolean
}) {
  const ranges = useMemo<TranscriptRange[]>(
    () => (summary.sourced_claims ?? []).flatMap((claim) => claim.transcript_ranges ?? []),
    [summary.sourced_claims],
  )
  const hasEvidence = (summary.sourced_claims ?? []).length > 0 && (summary.sourced_claims ?? []).every((claim) => (claim.transcript_ranges ?? []).length > 0)
  const canApprove = (summary.status === 'pending_review' || (summary.status === 'approved' && approvalRequired)) && hasEvidence
  const canExport = summary.status === 'approved' && hasEvidence && !approvalRequired
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
          {approvalRequired ? 'Reapprove summary' : 'Approve summary'}
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

      {approvalRequired && <div role="alert" className="text-xs">This approved-status summary has no matching persisted approval. Check its source evidence, then explicitly reapprove as the authenticated records clerk before exporting.</div>}
      {exportResult && exportResult.summary_id === summary.summary_id && (
        <div
          className="rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)', overflowWrap: 'anywhere' }}
        >
          Signed record exported: {exportResult.record_id}.{' '}
          <span>{exportResult.artifact_digest ? `PDF SHA-256: ${exportResult.artifact_digest}` : 'PDF SHA-256: unavailable in this response.'}</span>{' '}
          The server runs PDF/A-3
          shape checks; timestamp authority remains deterministic unless a
          real authority is configured.
          <button type="button" onClick={() => onDownload(exportResult)} disabled={!canReview || busy} className="ml-3 rounded-md px-3 py-1.5 font-semibold" style={{ border: '1px solid var(--cc-line-strong)' }}>
            Download PDF
          </button>
          <button type="button" onClick={() => onVerify(exportResult)} disabled={!canReview || busy} className="ml-3 rounded-md px-3 py-1.5 font-semibold" style={{ border: '1px solid var(--cc-line-strong)' }}>
            Verify record
          </button>
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
    queryFn: () => listSummaryReviewItems(true),
    retry: false,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canReview = staffIdentityQuery.isSuccess && !staffIdentityQuery.isFetching && hasOperatorRole(staffIdentityQuery.data, 'records_clerk')

  const approveMutation = useMutation({
    mutationFn: (summary: SummaryDraft) => approveSummary(summary.summary_id, APPROVAL_PAYLOAD),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['summary-review-items'] }),
  })

  const exportMutation = useMutation({
    mutationFn: (summary: SummaryDraft) =>
      exportSignedRecord({
        summary_id: summary.summary_id,
        summary_status: summary.status,
      }),
    onSuccess: (record) => { setExportResult(record); verifyMutation.reset() },
  })

  const downloadMutation = useMutation({
    mutationFn: async (record: RecordExportResponse) => {
      const blob = await downloadSignedRecord(record.record_id)
      const url = URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = record.pdfa.file_name
        link.click()
      } finally {
        URL.revokeObjectURL(url)
      }
    },
  })

  const verifyMutation = useMutation({
    mutationFn: async (record: RecordExportResponse) => {
      const result = await verifySignedRecord(record.record_id)
      if (result.status !== 'verified') throw new Error('Record verification failed. Do not rely on this artifact; contact support.')
      return result
    },
  })

  const summaries = query.data?.items ?? []
  const busy = approveMutation.isPending || exportMutation.isPending || downloadMutation.isPending || verifyMutation.isPending

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

      {(staffIdentityQuery.isPending || staffIdentityQuery.isFetching) && <div role="status" className="mx-6 text-xs">Checking your role. Approval and export are disabled until your identity is confirmed.</div>}
      {staffIdentityQuery.isError && <ErrorState title="Could not confirm your role." error={staffIdentityQuery.error} onRetry={() => staffIdentityQuery.refetch()} />}
      {staffIdentityQuery.isSuccess && !staffIdentityQuery.isFetching && !canReview && (
        <div role="alert" className="mx-6 rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          Summary approval and signed-record export require the records clerk role. Evidence remains readable.
        </div>
      )}

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {approveMutation.error && (
        <ErrorState
          title="Could not approve summary."
          canRetry={canReview && !busy}
          error={approveMutation.error}
          onRetry={() => { if (canReview && !busy && approveMutation.variables) approveMutation.mutate(approveMutation.variables) }}
        />
      )}
      {exportMutation.error && <ErrorState title="Could not export signed record." canRetry={canReview && !busy} error={exportMutation.error} onRetry={() => { if (canReview && !busy && exportMutation.variables) exportMutation.mutate(exportMutation.variables) }} />}
      {downloadMutation.error && <ErrorState title="Signed record was exported, but the PDF download failed." canRetry={canReview && !busy} error={downloadMutation.error} onRetry={() => { if (canReview && !busy && downloadMutation.variables) downloadMutation.mutate(downloadMutation.variables) }} />}
      {verifyMutation.isPending && <div role="status" className="mx-6 text-xs">Checking signed-record integrity and timestamp proof structure.</div>}
      {verifyMutation.error && <ErrorState title="Could not verify signed record." canRetry={canReview && !busy} error={verifyMutation.error} onRetry={() => { if (canReview && !busy && verifyMutation.variables) verifyMutation.mutate(verifyMutation.variables) }} />}
      {verifyMutation.isSuccess && <div role="status" className="mx-6 text-xs">{verifyMutation.data.timestamp_proof.tsa_url == null
        ? 'Record verification passed. Deterministic test timestamp; no external timestamp authority was verified.'
        : 'Record verification passed. Artifact digest and timestamp proof structure checked; this is not an independent trust-chain validation.'}</div>}
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
              onDownload={(record) => downloadMutation.mutate(record)}
              onVerify={(record) => verifyMutation.mutate(record)}
              canReview={canReview}
              approvalRequired={query.data?.approval_required_summary_ids?.includes(summary.summary_id) ?? false}
            />
          ))}
        </div>
      )}
    </div>
  )
}
