// S7 media lifecycle spec §5 "Asset Readiness Detail" -- embedded in
// AssetDetailScreen's sidebar. Self-contained (own query/mutations) so a
// failure here never blocks the rest of the asset editor from rendering.

import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  getAssetReadiness,
  replaceAssetSource,
  setAssetLegalHold,
} from '../api/client'
import { ReadinessBadge } from '../components/ReadinessBadge'
import { useToast } from '../components/toast-context'

function ArchiveTierRow({ label, verified }: { label: string; verified: boolean }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span style={{ color: 'var(--cc-ink-2)' }}>{label}</span>
      <span style={{ color: verified ? 'var(--cc-ok)' : 'var(--cc-ink-3)' }}>
        {verified ? '✓ verified' : 'not verified'}
      </span>
    </div>
  )
}

export function MediaLifecyclePanel({ assetId }: { assetId: string }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [holdReason, setHoldReason] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const query = useQuery({
    queryKey: ['asset-readiness', assetId],
    queryFn: () => getAssetReadiness(assetId),
    retry: false,
  })

  const holdMutation = useMutation({
    mutationFn: (input: { legal_hold: boolean; reason?: string | null }) =>
      setAssetLegalHold(assetId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['asset-readiness', assetId] })
      setHoldReason('')
    },
    onError: (error: Error) =>
      toast.push({
        tone: 'error',
        message: 'Could not update legal hold.',
        detail: error instanceof ApiError ? error.detail : error.message,
      }),
  })

  const replaceMutation = useMutation({
    mutationFn: (file: File) => replaceAssetSource(assetId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['asset-readiness', assetId] })
      queryClient.invalidateQueries({ queryKey: ['staff-asset', assetId] })
      toast.push({ tone: 'success', message: 'Source file replaced. The old file was archived, not deleted.' })
    },
    onError: (error: Error) =>
      toast.push({
        tone: 'error',
        message: 'Could not replace the source file.',
        detail: error instanceof ApiError ? error.detail : error.message,
      }),
  })

  return (
    <section
      className="mt-4 flex flex-col gap-3 rounded-md p-3"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
    >
      <h3 className="m-0 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--cc-ink-3)' }}>
        Media lifecycle
      </h3>

      {query.isLoading && (
        <div className="h-16 w-full animate-pulse rounded-md" style={{ background: 'var(--cc-surface-3)' }} />
      )}
      {query.isError && (
        <div role="alert" className="text-[11px]" style={{ color: 'var(--cc-err)' }}>
          Could not load readiness:{' '}
          {query.error instanceof ApiError && query.error.detail ? query.error.detail : query.error.message}
        </div>
      )}
      {query.isSuccess && (
        <>
          <div className="flex items-center justify-between">
            <ReadinessBadge state={query.data.readiness_state} />
            {query.data.legal_hold && (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
              >
                🔒 Legal hold
              </span>
            )}
          </div>
          {query.data.readiness_reason && (
            <p className="m-0 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
              {query.data.readiness_reason}
            </p>
          )}

          <div className="flex items-center justify-between text-[11px]">
            <span style={{ color: 'var(--cc-ink-2)' }}>Loudness gate</span>
            <span
              style={{
                color:
                  query.data.loudness_status === 'ok'
                    ? 'var(--cc-ok)'
                    : query.data.loudness_status === 'failed'
                      ? 'var(--cc-err)'
                      : 'var(--cc-ink-3)',
              }}
            >
              {query.data.loudness_status === 'ok' && query.data.measured_lufs != null
                ? `OK (${query.data.measured_lufs.toFixed(1)} LUFS)`
                : query.data.loudness_status === 'failed'
                  ? 'Failed — normalize before air'
                  : 'Not checked yet'}
            </span>
          </div>

          {(query.data.in_flight_transcode_jobs ?? []).length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
                Transcode jobs in flight
              </span>
              {(query.data.in_flight_transcode_jobs ?? []).map((job) => (
                <div key={job.job_id} className="flex items-center justify-between text-[11px]">
                  <span className="cc-mono">{job.output_format}</span>
                  <span>{job.progress_percent}%</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-col gap-1 border-t pt-2" style={{ borderColor: 'var(--cc-line)' }}>
            <span className="text-[11px] font-medium" style={{ color: 'var(--cc-ink-2)' }}>
              Archival (CLAUDE.md §4.6): portal + Internet Archive + local NAS, all verified
            </span>
            <ArchiveTierRow label="Portal (published)" verified={query.data.archive_portal_verified} />
            <ArchiveTierRow label="Internet Archive" verified={query.data.archive_ia_verified} />
            <ArchiveTierRow label="Local NAS" verified={query.data.archive_nas_verified} />
            <div className="mt-1 text-[11px] font-medium" style={{ color: query.data.archive_complete ? 'var(--cc-ok)' : 'var(--cc-ink-3)' }}>
              {query.data.archive_complete ? '✓ Archive-complete' : 'Not archive-complete yet'}
            </div>
          </div>

          <div className="flex flex-col gap-2 border-t pt-2" style={{ borderColor: 'var(--cc-line)' }}>
            <span className="text-[11px] font-medium" style={{ color: 'var(--cc-ink-2)' }}>
              Legal hold
            </span>
            {query.data.legal_hold ? (
              <button
                type="button"
                onClick={() => holdMutation.mutate({ legal_hold: false })}
                disabled={holdMutation.isPending}
                className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
              >
                {holdMutation.isPending ? 'Clearing…' : 'Clear legal hold'}
              </button>
            ) : (
              <>
                <input
                  aria-label="Legal hold reason"
                  placeholder="Reason (e.g. open records request)"
                  value={holdReason}
                  onChange={(e) => setHoldReason(e.target.value)}
                  className="rounded-md px-2.5 py-1 text-[11px]"
                  style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
                />
                <button
                  type="button"
                  onClick={() => holdMutation.mutate({ legal_hold: true, reason: holdReason || null })}
                  disabled={holdMutation.isPending}
                  className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                  style={{ border: '1px solid var(--cc-warn)', color: 'var(--cc-warn)', background: 'var(--cc-surface)' }}
                >
                  {holdMutation.isPending ? 'Setting…' : 'Place legal hold (blocks expiry)'}
                </button>
              </>
            )}
          </div>

          <div className="flex flex-col gap-2 border-t pt-2" style={{ borderColor: 'var(--cc-line)' }}>
            <span className="text-[11px] font-medium" style={{ color: 'var(--cc-ink-2)' }}>
              Replace source file
            </span>
            <p className="m-0 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
              For a corrupt or wrong file. The current file is archived alongside the asset, never
              deleted.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              aria-label="Replacement video file"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) replaceMutation.mutate(file)
              }}
              disabled={replaceMutation.isPending}
              className="text-[11px]"
            />
            {replaceMutation.isPending && (
              <span className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                Uploading and validating…
              </span>
            )}
          </div>
        </>
      )}
    </section>
  )
}
