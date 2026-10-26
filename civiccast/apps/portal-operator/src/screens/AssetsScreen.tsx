import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listStaffAssets,
  packageStaffAsset,
  updateStaffAsset,
  getStaffIdentity,
  getReadinessDashboard,
  ApiError,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { StateBadge } from '../components/StateBadge'
import type { ReadinessState } from '../components/ReadinessBadge'
import { AssetStatusBadge } from '../components/assets/AssetStatusBadge'
import { deriveAssetStatus } from '../components/assets/assetStatus'
import { AssetUploadControl } from '../components/assets/AssetUploadControl'
import type { AssetRow, AssetState } from '../types/asset'

type FilterId = 'all' | AssetState

const FILTERS: ReadonlyArray<{ id: FilterId; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'validated', label: 'Validated' },
  { id: 'recorded', label: 'Recorded' },
  { id: 'pending_ingest', label: 'Analyzing' },
  { id: 'rejected', label: 'Rejected' },
]

function fmtSize(bytes: number | null): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function fmtDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

function fmtDate(iso: string | null): string {
  if (iso == null) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const isApiError = error instanceof ApiError
  const is503 = isApiError && error.status === 503
  return (
    <div
      role="alert"
      className="mx-6 my-6 flex flex-col gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
    >
      <div className="text-sm font-semibold">
        {is503 ? 'Durable storage is not ready.' : 'Could not load assets.'}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {isApiError && error.detail
          ? error.detail
          : `Request failed: ${error.message}`}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong>{' '}
        {is503
          ? 'Open Setup, prepare durable storage, then return here.'
          : 'Try again, or check the server logs for more detail.'}
      </div>
      <div>
        {is503 && (
          <a
            href="#/setup"
            className="mr-2 inline-flex rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            Go to Setup
          </a>
        )}
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          Retry
        </button>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div
      className="mx-6 my-10 flex flex-col items-center gap-3 rounded-md p-10 text-center"
      style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)' }}
    >
      <div className="text-sm font-semibold">No assets yet.</div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Use Upload video above, add a watch folder under Media Lifecycle Settings, or
        add a bundled sample from Setup.
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="mx-6 my-6 flex flex-col gap-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-12 w-full animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

interface AssetsScreenProps {
  onEditTrim?: (assetId: string) => void
  onOpenAsset?: (assetId: string) => void
}

export function AssetsScreen({
  onEditTrim,
  onOpenAsset,
}: AssetsScreenProps = {}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<FilterId>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [applyDescription, setApplyDescription] = useState(false)
  const [description, setDescription] = useState('')
  const [applyBody, setApplyBody] = useState(false)
  const [meetingBody, setMeetingBody] = useState('')
  const [editResults, setEditResults] = useState<Array<{ assetId: string; title: string; ok: boolean; detail: string }>>([])

  const query = useQuery<AssetRow[], Error>({
    queryKey: ['staff-assets'],
    queryFn: listStaffAssets,
    retry: false,
  })
  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  // S7 media lifecycle: readiness badges are a secondary, best-effort
  // signal layered onto the asset list -- a failure here must never block
  // or error the primary asset list render, so this query's error/loading
  // states are consumed silently (a missing badge just falls back to
  // nothing rendered in that cell).
  const readinessQuery = useQuery({
    queryKey: ['readiness-dashboard'],
    queryFn: getReadinessDashboard,
    retry: false,
  })
  const readinessByAssetId = useMemo(() => {
    const map = new Map<
      string,
      { readiness_state: ReadinessState; in_flight_jobs_count: number; readiness_reason: string | null }
    >()
    for (const row of readinessQuery.data?.by_asset ?? []) {
      map.set(row.asset_id, {
        readiness_state: row.readiness_state as ReadinessState,
        in_flight_jobs_count: row.in_flight_jobs_count,
        readiness_reason: row.readiness_reason,
      })
    }
    return map
  }, [readinessQuery.data])
  const canPackage =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'publish_operator') ||
      hasOperatorRole(identityQuery.data, 'setup_admin'))
  // Matches the upload endpoint's own role gate
  // (require_any_role("records_clerk", "meeting_operator", "support_admin")
  // in civiccast/schedule/router.py) so the control's disabled state is
  // never a surprise the server disagrees with.
  const canUpload =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'records_clerk') ||
      hasOperatorRole(identityQuery.data, 'meeting_operator') ||
      hasOperatorRole(identityQuery.data, 'support_admin'))
  const packageMutation = useMutation<AssetRow, Error, string>({
    mutationFn: (assetId) => packageStaffAsset(assetId),
    onSuccess: () => query.refetch(),
  })
  const queryClient = useQueryClient()

  const canEditMetadata = canUpload
  const metadataMutation = useMutation({
    mutationFn: async () => {
      const targets = (query.data ?? []).filter((row) => selected.has(row.asset_id))
      const results: Array<{ assetId: string; title: string; ok: boolean; detail: string }> = []
      setEditResults([])
      for (const row of targets) {
        try {
          await updateStaffAsset(row.asset_id, {
            expected_version: row.version,
            ...(applyDescription ? { description: description.trim() || null } : {}),
            ...(applyBody ? { meeting_body: meetingBody.trim() || null } : {}),
          })
          results.push({ assetId: row.asset_id, title: row.title, ok: true, detail: 'Saved' })
        } catch (error) {
          results.push({ assetId: row.asset_id, title: row.title, ok: false, detail: error instanceof ApiError ? error.detail ?? error.message : String(error) })
        }
        setEditResults([...results])
      }
      return results
    },
    onSuccess: (results) => {
      const saved = new Set(results.filter((result) => result.ok).map((result) => result.assetId))
      setSelected((prior) => new Set([...prior].filter((assetId) => !saved.has(assetId))))
      void queryClient.invalidateQueries({ queryKey: ['staff-assets'] })
    },
  })

  const visible = useMemo<AssetRow[]>(() => {
    const rows = query.data ?? []
    const trimmed = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (filter !== 'all' && r.state !== filter) return false
      if (
        trimmed &&
        !r.title.toLowerCase().includes(trimmed) &&
        !r.asset_id.toLowerCase().includes(trimmed)
      ) {
        return false
      }
      return true
    })
  }, [query.data, search, filter])

  return (
    <div className="flex flex-col">
      <header className="px-6 pb-4 pt-6">
        <div
          className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: 'var(--cc-ink-3)' }}
        >
          Library
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Assets</h1>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Recorded files uploaded for trim, scheduling, and publish. Files are kept
          untouched; trim and chapter edits are non-destructive.
        </p>
      </header>

      <AssetUploadControl
        canUpload={canUpload}
        roleCheckReady={identityQuery.isSuccess}
        onUploaded={() => {
          void queryClient.invalidateQueries({ queryKey: ['staff-assets'] })
          void queryClient.invalidateQueries({ queryKey: ['readiness-dashboard'] })
        }}
      />

      <div
        className="flex flex-wrap items-center gap-3 px-6 py-3"
        style={{ borderBottom: '1px solid var(--cc-line)' }}
      >
        <label
          className="cc-search-shell flex flex-1 items-center gap-2 rounded-md px-3 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            minWidth: 240,
          }}
        >
          <span aria-hidden="true" style={{ color: 'var(--cc-ink-3)' }}>
            ⌕
          </span>
          <input
            aria-label="Search assets"
            placeholder="Search by title or asset ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent text-sm outline-none"
            style={{ color: 'var(--cc-ink)' }}
          />
        </label>
        <div role="tablist" aria-label="Filter by state" className="flex gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.id
            return (
              <button
                key={f.id}
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(f.id)}
                className="rounded-md px-3 py-1.5 text-xs font-medium"
                style={{
                  background: active ? 'var(--cc-ink)' : 'transparent',
                  color: active ? 'var(--cc-ink-inv)' : 'var(--cc-ink-2)',
                  border: '1px solid transparent',
                }}
              >
                {f.label}
              </button>
            )
          })}
        </div>
      </div>

      {canEditMetadata && <section aria-label="Selected asset metadata" className="mx-6 my-3 grid gap-2 rounded-md border p-3 text-sm">
        <h2 className="font-semibold">Edit selected assets</h2>
        <p>{(query.data ?? []).filter((row) => selected.has(row.asset_id)).length} selected, including selections hidden by filters. Checked fields replace the value on every selected asset; blank clears it.</p>
        <label><input type="checkbox" checked={applyDescription} onChange={(event) => setApplyDescription(event.target.checked)} disabled={metadataMutation.isPending} /> Apply common description</label>
        <textarea aria-label="Common description" maxLength={2000} value={description} disabled={!applyDescription || metadataMutation.isPending} onChange={(event) => setDescription(event.target.value)} className="rounded-md border p-2" />
        <label><input type="checkbox" checked={applyBody} onChange={(event) => setApplyBody(event.target.checked)} disabled={metadataMutation.isPending} /> Apply common meeting body</label>
        <input aria-label="Common meeting body" maxLength={120} value={meetingBody} disabled={!applyBody || metadataMutation.isPending} onChange={(event) => setMeetingBody(event.target.value)} className="rounded-md border p-2" />
        <div className="flex gap-3">
          <button type="button" disabled={metadataMutation.isPending || !visible.length} onClick={() => setSelected(new Set([...selected, ...visible.map((row) => row.asset_id)]))}>Select visible assets</button>
          <button type="button" disabled={metadataMutation.isPending} onClick={() => setSelected(new Set())}>Clear selection</button>
          <button type="button" disabled={metadataMutation.isPending || !(applyDescription || applyBody) || !(query.data ?? []).some((row) => selected.has(row.asset_id))} onClick={() => metadataMutation.mutate()}>{metadataMutation.isPending ? 'Saving selected assets…' : 'Apply metadata to selected assets'}</button>
        </div>
        {editResults.length > 0 && <div role="status"><p>{editResults.filter((result) => result.ok).length} saved; {editResults.filter((result) => !result.ok).length} failed. Review failures before selecting and applying again; saved records are not rolled back.</p><ul>{editResults.map((result) => <li key={result.assetId}>{result.title} ({result.assetId}): {result.detail}</li>)}</ul></div>}
      </section>}

      {query.isLoading && <LoadingState />}
      {query.isError && (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      )}
      {query.isSuccess && visible.length === 0 && query.data.length === 0 && (
        <EmptyState />
      )}
      {query.isSuccess && visible.length === 0 && query.data.length > 0 && (
        <div
          className="mx-6 my-6 rounded-md p-4 text-center text-xs"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
        >
          No assets match the current search and filter.
        </div>
      )}
      {query.isSuccess && visible.length > 0 && (
        <div className="px-6 py-4">
          <div className="overflow-x-auto rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
          <table
            className="min-w-[760px] w-full border-collapse text-sm"
            style={{ background: 'var(--cc-surface)' }}
          >
            <thead>
              <tr
                className="text-left text-[11px] uppercase tracking-wider"
                style={{ color: 'var(--cc-ink-3)' }}
              >
                {canEditMetadata && <th className="px-3 py-2">Select</th>}
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Codec</th>
                <th className="px-3 py-2">Published</th>
                <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.asset_id}
                  style={{ borderTop: '1px solid var(--cc-line)' }}
                >
                  {canEditMetadata && <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${row.title} (${row.asset_id})`} checked={selected.has(row.asset_id)} disabled={metadataMutation.isPending} onChange={(event) => setSelected((prior) => { const next = new Set(prior); if (event.target.checked) next.add(row.asset_id); else next.delete(row.asset_id); return next })} /></td>}
                  <td className="px-3 py-3 align-top">
                    {onOpenAsset ? (
                      <button
                        type="button"
                        onClick={() => onOpenAsset(row.asset_id)}
                        className="text-left font-medium"
                        style={{
                          background: 'transparent',
                          border: 0,
                          color: 'var(--cc-brand-2)',
                          textDecoration: 'underline',
                          textUnderlineOffset: 3,
                          cursor: 'pointer',
                        }}
                        aria-label={`Open detail for ${row.title} (${row.asset_id})`}
                      >
                        {row.title}
                      </button>
                    ) : (
                      <div className="font-medium">{row.title}</div>
                    )}
                    <div
                      className="cc-mono mt-0.5 text-[11px]"
                      style={{ color: 'var(--cc-ink-3)' }}
                    >
                      {row.asset_id}
                    </div>
                  </td>
                  <td className="px-3 py-3 align-top">
                    <StateBadge state={row.state} />
                  </td>
                  <td className="px-3 py-3 align-top">
                    {/* Candidate #17 field finding (second report): a
                        Validated + Packaged asset showed "Not ready". The
                        status is now derived from the asset row itself
                        (state / manifest_url / published_at / file_status),
                        with the lifecycle worker's readiness row layered in
                        only for transcode-in-flight and missing-file detail
                        -- see deriveAssetStatus. An absent or stale worker
                        row can no longer demote a packaged/published asset. */}
                    <AssetStatusBadge
                      status={deriveAssetStatus(row, readinessByAssetId.get(row.asset_id))}
                      inFlightJobsCount={
                        readinessByAssetId.get(row.asset_id)?.in_flight_jobs_count
                      }
                    />
                  </td>
                  <td
                    className="cc-mono cc-tabular px-3 py-3 align-top text-xs"
                    style={{ color: 'var(--cc-ink-2)' }}
                  >
                    {fmtDuration(row.duration_seconds)}
                  </td>
                  <td
                    className="cc-mono cc-tabular px-3 py-3 align-top text-xs"
                    style={{ color: 'var(--cc-ink-2)' }}
                  >
                    {fmtSize(row.file_size_bytes)}
                  </td>
                  <td
                    className="px-3 py-3 align-top text-xs"
                    style={{ color: 'var(--cc-ink-2)' }}
                  >
                    {row.codec_video ?? '—'}
                    {row.codec_audio ? (
                      <>
                        {' '}
                        ·{' '}
                        <span style={{ color: 'var(--cc-ink-3)' }}>
                          {row.codec_audio}
                        </span>
                      </>
                    ) : null}
                  </td>
                  <td
                    className="px-3 py-3 align-top text-xs"
                    style={{ color: 'var(--cc-ink-2)' }}
                  >
                    {fmtDate(row.published_at)}
                  </td>
                  <td className="px-3 py-3 align-top">
                    <div className="flex flex-col items-start gap-1">
                      {row.state === 'validated' && onEditTrim && (
                        <button
                          type="button"
                          onClick={() => onEditTrim(row.asset_id)}
                          className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                          style={{
                            border: '1px solid var(--cc-line)',
                            color: 'var(--cc-ink-2)',
                            background: 'var(--cc-surface)',
                          }}
                          aria-label={`Edit trim and chapters for ${row.title} (${row.asset_id})`}
                        >
                          Edit trim
                        </button>
                      )}
                      {(row.state === 'validated' || row.state === 'recorded') &&
                        row.file_path && (
                        <button
                          type="button"
                          onClick={() => packageMutation.mutate(row.asset_id)}
                          disabled={!canPackage || packageMutation.isPending}
                          className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                          style={{
                            border: '1px solid var(--cc-line)',
                            color: 'var(--cc-ink-2)',
                            background: 'var(--cc-surface)',
                          }}
                          aria-label={`${row.manifest_url ? 'Repackage' : 'Package'} ${row.title} (${row.asset_id}) for resident playback`}
                        >
                          {packageMutation.isPending && packageMutation.variables === row.asset_id
                            ? 'Packaging...'
                            : row.manifest_url ? 'Repackage for playback' : 'Package for playback'}
                        </button>
                      )}
                      {(row.state === 'validated' || row.state === 'recorded') &&
                        row.file_path &&
                        identityQuery.isSuccess &&
                        !canPackage && (
                          <span className="max-w-52 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                            A publish operator or setup administrator must package this recording.
                          </span>
                        )}
                      {packageMutation.isError && packageMutation.variables === row.asset_id && (
                        <span role="alert" className="max-w-52 text-[10px]" style={{ color: 'var(--cc-err)' }}>
                          {packageMutation.error instanceof ApiError && packageMutation.error.detail
                            ? packageMutation.error.detail
                            : 'Packaging failed. The original file was kept; try again.'}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  )
}
