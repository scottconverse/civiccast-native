import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  listStaffAssets,
  packageStaffAsset,
  getStaffIdentity,
  ApiError,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { StateBadge } from '../components/StateBadge'
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

function PackagingHint({ row }: { row: AssetRow }) {
  if (row.manifest_url) {
    return (
      <span className="cc-mono text-[10px]" style={{ color: 'var(--cc-ok)' }}>
        Packaged
      </span>
    )
  }
  if (row.state === 'recorded') {
    // Live recordings may be packaged locally; without a public manifest URL
    // they are not servable to residents either way (manifest honesty rule).
    return (
      <span className="cc-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
        Not servable yet
      </span>
    )
  }
  if (row.state === 'validated') {
    return (
      <span className="cc-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
        Not packaged yet
      </span>
    )
  }
  return null
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
        Add a bundled sample or upload a short test video from Setup, then return
        here after ingest completes.
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
  const canPackage =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'publish_operator') ||
      hasOperatorRole(identityQuery.data, 'setup_admin'))
  const packageMutation = useMutation<AssetRow, Error, string>({
    mutationFn: (assetId) => packageStaffAsset(assetId),
    onSuccess: () => query.refetch(),
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
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Codec</th>
                <th className="px-3 py-2">Published</th>
                <th className="px-3 py-2">Packaging</th>
                <th className="px-3 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.asset_id}
                  style={{ borderTop: '1px solid var(--cc-line)' }}
                >
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
                    <PackagingHint row={row} />
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
                      {row.state === 'validated' && !row.manifest_url && row.file_path && (
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
                          aria-label={`Package ${row.title} (${row.asset_id}) for resident playback`}
                        >
                          {packageMutation.isPending && packageMutation.variables === row.asset_id
                            ? 'Packaging...'
                            : 'Package for playback'}
                        </button>
                      )}
                      {row.state === 'validated' &&
                        !row.manifest_url &&
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
