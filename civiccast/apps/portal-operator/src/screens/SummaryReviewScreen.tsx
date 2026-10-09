import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  approveSummary,
  downloadSignedRecord,
  editSummary,
  exportSignedRecord,
  getStaffIdentity,
  listSignedRecords,
  listSummaryReviewItems,
  verifySignedRecord,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { SourcedClaimList } from '../components/review/SourcedClaimList'
import { TranscriptCuePlayer } from '../components/review/TranscriptCuePlayer'
import type { RecordExportResponse, SummaryDraft, TranscriptRange } from '../types/api.generated'
import { SUMMARY_STATUS_META } from '../types/summary'

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

function ErrorState({ error, onRetry, actionFailed = false }: { error: Error; onRetry: () => void; actionFailed?: boolean }) {
  const conflict = actionFailed && error instanceof ApiError && error.status === 409
  return (
    <div
      role="alert"
      className="mx-6 my-6 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
    >
      <div className="text-sm font-semibold">
        {actionFailed ? 'Could not complete summary review action.' : 'Could not load summary review.'}
      </div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {apiMessage(error, 'The summary review request failed.')}
      </div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong>{' '}
        {conflict
          ? 'Reload the summaries and review the updated draft before trying again.'
          : actionFailed
          ? 'Dismiss this message and try the action again. If it continues, ask your station administrator to check CivicCast server and database health.'
          : 'Retry the request. If it continues to fail, ask your station administrator to check CivicCast server and database health.'}
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-md px-3 py-1.5 text-xs font-medium"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        {conflict ? 'Reload summaries' : actionFailed ? 'Dismiss' : 'Retry'}
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
  verificationResults,
  busy,
  onSeek,
  onApprove,
  onSaveEdit,
  onExport,
  onLoadRecords,
  onDownload,
  onVerify,
  canReview,
}: {
  summary: SummaryDraft
  activeCueId: string | null
  exportResult: RecordExportResponse | null
  verificationResults: Record<string, RecordExportResponse>
  busy: boolean
  onSeek: (cueId: string) => void
  onApprove: (summary: SummaryDraft) => void
  onSaveEdit: (summary: SummaryDraft, narrative: string) => Promise<void>
  onExport: (summary: SummaryDraft) => void
  onLoadRecords: (summary: SummaryDraft) => void
  onDownload: (record: RecordExportResponse) => void
  onVerify: (record: RecordExportResponse) => void
  canReview: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    fingerprint: summary.audit_fingerprint,
    narrative: summary.narrative,
  })
  const narrative = draft.fingerprint === summary.audit_fingerprint ? draft.narrative : summary.narrative
  const setNarrative = (value: string) => setDraft({ fingerprint: summary.audit_fingerprint, narrative: value })
  const [savedRecordsOpen, setSavedRecordsOpen] = useState(false)
  const savedRecordsQuery = useQuery({
    queryKey: ['signed-records', summary.summary_id],
    queryFn: () => listSignedRecords(summary.summary_id, 10),
    enabled: canReview && summary.status === 'approved' && savedRecordsOpen,
    retry: false,
  })

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

      {editing ? (
        <label className="grid gap-1 text-xs font-medium" htmlFor={`summary-narrative-${summary.summary_id}`}>
          Edit summary narrative
          <textarea
            id={`summary-narrative-${summary.summary_id}`}
            value={narrative}
            maxLength={12000}
            rows={5}
            onChange={(event) => setNarrative(event.target.value)}
            className="rounded-md p-3 text-sm font-normal"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          />
        </label>
      ) : (
        <p className="m-0 rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          {summary.narrative}
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SourcedClaimList claims={summary.sourced_claims ?? []} onSeek={onSeek} />
        <TranscriptCuePlayer ranges={ranges} activeCueId={activeCueId} />
      </div>

      <div className="flex flex-wrap gap-2">
        {summary.status === 'pending_review' && (
          editing ? (
            <>
              <button
                type="button"
                onClick={() => {
                  void onSaveEdit(summary, narrative)
                    .then(() => setEditing(false))
                    .catch(() => undefined)
                }}
                disabled={!canReview || busy || !narrative.trim() || narrative === summary.narrative}
                className="rounded-md px-3 py-1.5 text-xs font-semibold"
                style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
              >
                Save changes
              </button>
              <button
                type="button"
                onClick={() => {
                  setNarrative(summary.narrative)
                  setEditing(false)
                }}
                disabled={busy}
                className="rounded-md px-3 py-1.5 text-xs font-semibold"
                style={{ border: '1px solid var(--cc-line-strong)' }}
              >
                Cancel edit
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={!canReview || busy}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ border: '1px solid var(--cc-line-strong)' }}
            >
              Edit summary
            </button>
          )
        )}
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
        {canExport && (
          <button
            type="button"
            onClick={() => {
              const opening = !savedRecordsOpen
              setSavedRecordsOpen(opening)
              if (opening) onLoadRecords(summary)
            }}
            disabled={!canReview}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ border: '1px solid var(--cc-line-strong)' }}
          >
            {savedRecordsOpen ? 'Hide saved records' : 'Load saved records'}
          </button>
        )}
      </div>

      {savedRecordsOpen && canExport && (
        <div className="grid gap-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)' }}>
          <div className="font-semibold">Previously exported signed records</div>
          {savedRecordsQuery.isLoading && <div>Loading saved records…</div>}
          {savedRecordsQuery.isError && (
            <div role="alert">Could not load saved records. Try again or ask your station administrator to check signed-record storage.</div>
          )}
          {savedRecordsQuery.isSuccess && savedRecordsQuery.data.length === 0 && (
            <div>No signed records have been exported for this summary yet.</div>
          )}
          {savedRecordsQuery.data?.map((record) => (
            <div key={record.record_id} className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface)' }}>
              <div>
                {record.pdfa.file_name} · {record.record_id} · {record.status}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onDownload(record)}
                  disabled={!canReview || busy}
                  aria-label={`Download saved record ${record.record_id}`}
                  className="rounded-md px-3 py-1.5 text-xs font-semibold"
                  style={{ border: '1px solid var(--cc-line-strong)' }}
                >
                  Download
                </button>
                <button
                  type="button"
                  onClick={() => onVerify(record)}
                  disabled={!canReview || busy}
                  aria-label={`Verify saved record ${record.record_id}`}
                  className="rounded-md px-3 py-1.5 text-xs font-semibold"
                  style={{ border: '1px solid var(--cc-line-strong)' }}
                >
                  Verify
                </button>
              </div>
              {verificationResults[record.record_id] && (
                <div role="status" aria-live="polite">
                  Record verification: {verificationResults[record.record_id].status === 'verified' ? 'Verified' : 'Failed'}
                </div>
              )}
            </div>
          ))}
          {savedRecordsQuery.isError && (
            <button
              type="button"
              onClick={() => void savedRecordsQuery.refetch()}
              className="justify-self-start rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ border: '1px solid var(--cc-line-strong)' }}
            >
              Retry loading records
            </button>
          )}
        </div>
      )}

      {exportResult && exportResult.summary_id === summary.summary_id && (
        <div className="grid gap-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}>
          <div>
            Signed record exported: {exportResult.record_id}. Digest{' '}
            {exportResult.timestamp_proof.artifact_digest}. The server validates the
            PDF/A-3B artifact; timestamp authority remains deterministic unless a
            real authority is configured.
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onDownload(exportResult)}
              disabled={!canReview || busy}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line-strong)' }}
            >
              Download signed record
            </button>
            <button
              type="button"
              onClick={() => onVerify(exportResult)}
              disabled={!canReview || busy}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line-strong)' }}
            >
              Verify signed record
            </button>
          </div>
          {verificationResults[exportResult.record_id] && (
            <div role="status" aria-live="polite">
              Record verification: {verificationResults[exportResult.record_id].status === 'verified' ? 'Verified' : 'Failed'}
            </div>
          )}
        </div>
      )}
    </article>
  )
}

export function SummaryReviewScreen() {
  const [activeCueId, setActiveCueId] = useState<string | null>(null)
  const [exportResults, setExportResults] = useState<Record<string, RecordExportResponse>>({})
  const [verificationResults, setVerificationResults] = useState<Record<string, RecordExportResponse>>({})
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
  const canReview =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'records_clerk')

  const approveMutation = useMutation({
    mutationFn: (summary: SummaryDraft) => approveSummary(summary.summary_id, {
      expected_audit_fingerprint: summary.audit_fingerprint,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['summary-review-items'] }),
  })

  const editMutation = useMutation({
    mutationFn: ({ summary, narrative }: { summary: SummaryDraft; narrative: string }) =>
      editSummary(summary.summary_id, {
        narrative,
        expected_audit_fingerprint: summary.audit_fingerprint,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['summary-review-items'] }),
  })

  const exportMutation = useMutation({
    mutationFn: (summary: SummaryDraft) =>
      exportSignedRecord({
        summary_id: summary.summary_id,
      }),
    onSuccess: (record) => {
      setExportResults((records) => ({ ...records, [record.summary_id]: record }))
      void queryClient.invalidateQueries({ queryKey: ['signed-records', record.summary_id] })
    },
  })

  const verifyMutation = useMutation({
    mutationFn: (record: RecordExportResponse) => verifySignedRecord(record.record_id),
    onSuccess: (record) => setVerificationResults((results) => ({ ...results, [record.record_id]: record })),
  })

  const downloadMutation = useMutation({
    mutationFn: async (record: RecordExportResponse) => {
      const blob = await downloadSignedRecord(record.record_id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = record.pdfa.file_name
      link.click()
      URL.revokeObjectURL(url)
    },
  })

  const summaries = query.data?.items ?? []
  const busy =
    approveMutation.isPending ||
    editMutation.isPending ||
    exportMutation.isPending ||
    verifyMutation.isPending ||
    downloadMutation.isPending
  const mutationError =
    approveMutation.error ??
    editMutation.error ??
    exportMutation.error ??
    verifyMutation.error ??
    downloadMutation.error

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

      {(staffIdentityQuery.isError || (staffIdentityQuery.isSuccess && !canReview)) && (
        <div className="mx-6 rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          {staffIdentityQuery.isError
            ? 'Could not confirm your staff role. Summary changes and signed-record actions are disabled.'
            : 'Summary approval and signed-record actions require the records clerk role. Evidence remains readable.'}
        </div>
      )}

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {mutationError && (
        <ErrorState
          error={mutationError}
          actionFailed
          onRetry={() => {
            if (mutationError instanceof ApiError && mutationError.status === 409) {
              void queryClient.invalidateQueries({ queryKey: ['summary-review-items'] })
            }
            approveMutation.reset()
            editMutation.reset()
            exportMutation.reset()
            verifyMutation.reset()
            downloadMutation.reset()
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
              exportResult={exportResults[summary.summary_id] ?? null}
              verificationResults={verificationResults}
              busy={busy}
              onSeek={setActiveCueId}
              onApprove={(target) => approveMutation.mutate(target)}
              onSaveEdit={async (target, narrative) => {
                await editMutation.mutateAsync({ summary: target, narrative })
              }}
              onExport={(target) => exportMutation.mutate(target)}
              onLoadRecords={(target) => {
                void queryClient.invalidateQueries({ queryKey: ['signed-records', target.summary_id] })
              }}
              onDownload={(record) => downloadMutation.mutate(record)}
              onVerify={(record) => verifyMutation.mutate(record)}
              canReview={canReview}
            />
          ))}
        </div>
      )}
    </div>
  )
}
