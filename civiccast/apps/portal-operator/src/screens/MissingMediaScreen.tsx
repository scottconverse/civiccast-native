// S7 media lifecycle spec §5 "Missing Media Alert" (new screen).
//
// Background worker (civiccast.schedule.media_lifecycle_worker) scans on
// its normal poll interval; this screen reads a LIVE join
// (schedule_items x assets), not a durable flag -- an item drops off this
// list the moment its asset becomes ready, no operator action required to
// clear it (see the worker module's docstring for why a durable flag would
// be actively misleading here).

import { useQuery } from '@tanstack/react-query'
import { ApiError, listMissingMedia } from '../api/client'
import type { MissingMediaAlertRow } from '../types/api.generated'

function fmtScheduledStart(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
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
        {is503 ? 'Durable storage is not ready.' : 'Could not load missing-media alerts.'}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {isApiError && error.detail ? error.detail : `Request failed: ${error.message}`}
      </div>
      <div>
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
      <div className="text-sm font-semibold">Nothing missing.</div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Every asset scheduled in the coming week is validated or recorded and ready for air.
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="mx-6 my-6 flex flex-col gap-2">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-14 w-full animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

function AlertCard({ row, onOpenAsset }: { row: MissingMediaAlertRow; onOpenAsset?: (assetId: string) => void }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-warn)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">
            {row.asset_title} — {fmtScheduledStart(row.scheduled_start)}
          </div>
          <div className="cc-mono mt-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {row.channel_id} · source asset '{row.asset_id}' · state: {row.asset_state}
          </div>
        </div>
        <span
          className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
          style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
        >
          🔴 Not ready
        </span>
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {row.reason}
      </div>
      {onOpenAsset && (
        <div>
          <button
            type="button"
            onClick={() => onOpenAsset(row.asset_id)}
            className="rounded-md px-2.5 py-1 text-[11px] font-medium"
            style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
          >
            Open asset
          </button>
        </div>
      )}
    </div>
  )
}

interface MissingMediaScreenProps {
  onOpenAsset?: (assetId: string) => void
}

export function MissingMediaScreen({ onOpenAsset }: MissingMediaScreenProps = {}) {
  const query = useQuery<MissingMediaAlertRow[], Error>({
    queryKey: ['missing-media'],
    queryFn: listMissingMedia,
    retry: false,
  })

  return (
    <div className="flex flex-col">
      <header className="px-6 pb-4 pt-6">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Media Lifecycle
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Missing Media</h1>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Meetings scheduled in the next 7 days whose source asset is not validated, not
          recorded, or missing its file. Fix these before air check.
        </p>
      </header>

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.isSuccess && query.data.length === 0 && <EmptyState />}
      {query.isSuccess && query.data.length > 0 && (
        <div className="flex flex-col gap-3 px-6 py-4">
          {query.data.map((row) => (
            <AlertCard key={row.schedule_id} row={row} onOpenAsset={onOpenAsset} />
          ))}
        </div>
      )}
    </div>
  )
}
