import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  disableProgramSlot,
  getChannelProgramLog,
  listChannelProfiles,
  listProgramSlots,
  materializeProgramLog,
} from '../api/client'
import { ConfirmDialog, type PendingConfirm } from '../components/ConfirmDialog'
import { ProgramSlotDrawer } from '../components/programlog/ProgramSlotDrawer'
import { useToast } from '../components/toast-context'
import type {
  ChannelLogEntry,
  ChannelProfile,
  MaterializeResult,
  ProgramSlot,
  SlotOccurrence,
} from '../types/api.generated'
import { EmptyState } from '../components/EmptyState'

const DEFAULT_CHANNEL = 'public'
const LOG_HOURS = 168 // operator view: one rolling week

const RECURRENCE_LABEL: Record<ProgramSlot['recurrence'], string> = {
  once: 'Once',
  daily: 'Daily',
  weekly: 'Weekly',
  weekdays: 'Weekdays',
}

const STATUS_META: Record<
  string,
  { label: string; tone: 'ok' | 'warn' | 'err' | 'neutral' }
> = {
  scheduled: { label: 'Scheduled', tone: 'ok' },
  skipped_conflict: { label: 'Skipped · conflict', tone: 'warn' },
  skipped_asset: { label: 'Skipped · not playable', tone: 'warn' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
}

function StatusChip({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: 'neutral' as const }
  const palette: Record<'ok' | 'warn' | 'err' | 'neutral', { bg: string; fg: string }> = {
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)' },
    err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)' },
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
  }
  const tone = palette[meta.tone]
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {meta.label}
    </span>
  )
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

function fmtDuration(seconds: number | null | undefined): string {
  if (!seconds) return 'recording length'
  const mins = Math.round(seconds / 60)
  if (mins < 60) return `${mins} min`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h} h ${m} min` : `${h} h`
}

export type LogDayGroup = {
  key: string
  day: Date
  entries: ChannelLogEntry[]
}
export type GroupedLog = {
  groups: LogDayGroup[]
  unreadable: ChannelLogEntry[]
}

/**
 * Group program-log entries by local day.
 *
 * Unparseable `occurrence_start` values are quarantined rather than grouped.
 * This is the same defect that blanked the Schedule screen: an Invalid Date
 * still produced a map key (`NaN-NaN-NaN`) and a stored `day`, and the render
 * then called `day.toISOString()` for the React key — `RangeError` thrown
 * during render, so the whole Program Guide went blank with no error shown.
 *
 * The value is rejected BEFORE the Date constructor because `new Date(null)`
 * is not an Invalid Date — it is the Unix epoch, which would silently render
 * a program dated 1969 instead of reporting it. Timestamps are typed `string`
 * but arrive through a blind `as T` cast over the wire, so the type is a
 * contract, not a guarantee.
 */
function groupLogByDay(entries: ChannelLogEntry[]): GroupedLog {
  const map = new Map<string, LogDayGroup>()
  const unreadable: ChannelLogEntry[] = []
  for (const entry of entries) {
    const raw: unknown = entry.occurrence_start
    if (typeof raw !== 'string' || raw.trim() === '') {
      unreadable.push(entry)
      continue
    }
    const d = new Date(raw)
    if (Number.isNaN(d.getTime())) {
      unreadable.push(entry)
      continue
    }
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    const existing = map.get(key)
    if (existing) {
      existing.entries.push(entry)
    } else {
      const day = new Date(d)
      day.setHours(0, 0, 0, 0)
      map.set(key, { key, day, entries: [entry] })
    }
  }
  const groups = Array.from(map.values())
  groups.sort((a, b) => a.day.getTime() - b.day.getTime())
  return { groups, unreadable }
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
        {is503 ? 'Durable storage is not ready.' : 'Could not load the program guide.'}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {isApiError && error.detail ? error.detail : error.message}
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

interface SlotListProps {
  slots: ProgramSlot[]
  onDisable: (slot: ProgramSlot) => void
  disabling: boolean
}

function SlotList({ slots, onDisable, disabling }: SlotListProps) {
  if (slots.length === 0) {
    return (
      <EmptyState
        headline="Nothing on the guide yet."
        body="The program guide is the weekly grid of what airs on this channel. Place a recording with “Add to guide” and its recurring slot appears here."
      />
    )
  }
  return (
    <div
      className="overflow-hidden rounded-md"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      {slots.map((slot, idx) => (
        <div
          key={slot.slot_id}
          className="flex flex-wrap items-center gap-3 px-3 py-3 text-xs"
          style={{ borderTop: idx > 0 ? '1px solid var(--cc-line)' : undefined }}
        >
          <span
            className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
            style={{ background: 'var(--cc-brand-soft)', color: 'var(--cc-brand-2)' }}
          >
            {RECURRENCE_LABEL[slot.recurrence]}
          </span>
          <div className="min-w-0 flex-1">
            <div className="cc-truncate font-medium">
              {slot.title_override?.trim() || slot.asset_id}
            </div>
            <div className="cc-mono cc-truncate text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
              {slot.asset_id} · first{' '}
              {new Date(slot.first_start_at).toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
              })}
              {slot.repeat_until
                ? ` · until ${new Date(slot.repeat_until).toLocaleDateString()}`
                : ''}
            </div>
          </div>
          <span className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {fmtDuration(slot.duration_seconds)}
          </span>
          {slot.enabled === false ? (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-3)' }}
            >
              Disabled
            </span>
          ) : (
            <button
              type="button"
              disabled={disabling}
              onClick={() => onDisable(slot)}
              className="rounded-md px-2.5 py-1 text-[11px] font-medium"
              style={{
                border: '1px solid var(--cc-line)',
                color: 'var(--cc-ink-2)',
                background: 'var(--cc-surface)',
                cursor: disabling ? 'not-allowed' : 'pointer',
              }}
            >
              Disable
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function LogList({ entries }: { entries: ChannelLogEntry[] }) {
  const { groups, unreadable } = useMemo(
    () => groupLogByDay(entries),
    [entries],
  )
  const today = new Date()
  if (entries.length === 0) {
    return (
      <EmptyState
        headline="Nothing scheduled for the next 7 days."
        body="This log is the day-by-day schedule built from the guide's recurring slots. Add a slot, then press “Refresh guide” to build out the week."
      />
    )
  }
  return (
    <div className="flex flex-col gap-4">
      {unreadable.length > 0 && (
        <div
          role="status"
          className="rounded-md p-3 text-xs"
          style={{
            background: 'var(--cc-warn-soft, var(--cc-surface-2))',
            border: '1px solid var(--cc-warn, var(--cc-line))',
            color: 'var(--cc-ink-2)',
          }}
        >
          {unreadable.length === 1
            ? '1 guide entry has an air time this station cannot read and is not shown below.'
            : `${unreadable.length} guide entries have air times this station cannot read and are not shown below.`}{' '}
          The rest of the guide is complete.
        </div>
      )}
      {groups.map((g) => {
        const isToday =
          g.day.getFullYear() === today.getFullYear() &&
          g.day.getMonth() === today.getMonth() &&
          g.day.getDate() === today.getDate()
        return (
          <div key={g.key}>
            <div
              className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              <span>
                {g.day.toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
              {isToday && (
                <span
                  className="rounded-full px-1.5 py-0.5 text-[9px] uppercase"
                  style={{ background: 'var(--cc-brand-soft)', color: 'var(--cc-brand-2)' }}
                >
                  Today
                </span>
              )}
            </div>
            <div
              className="overflow-hidden rounded-md"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              {g.entries.map((entry, idx) => {
                const skipped = entry.status.startsWith('skipped')
                return (
                  <div
                    key={entry.occurrence_id}
                    className="flex flex-wrap items-center gap-3 px-3 py-3 text-xs"
                    style={{
                      borderTop: idx > 0 ? '1px solid var(--cc-line)' : undefined,
                      background: skipped ? 'var(--cc-warn-soft)' : undefined,
                    }}
                  >
                    <span
                      className="cc-mono cc-tabular w-20 shrink-0"
                      style={{ color: 'var(--cc-ink-2)' }}
                    >
                      {fmtTime(entry.occurrence_start)}
                    </span>
                    <StatusChip status={entry.status} />
                    <div className="min-w-0 flex-1">
                      <div className="cc-truncate font-medium">
                        {entry.title_override?.trim() || entry.asset_id}
                      </div>
                      {skipped && entry.detail && (
                        <div className="cc-truncate text-[10px]" style={{ color: 'var(--cc-warn)' }}>
                          {entry.detail}
                        </div>
                      )}
                    </div>
                    <span className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                      {fmtDuration(entry.duration_seconds)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function ProgramGuideScreen() {
  const [channelId, setChannelId] = useState<string>(DEFAULT_CHANNEL)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()

  const channelsQuery = useQuery<ChannelProfile[], Error>({
    queryKey: ['cable-channels'],
    queryFn: listChannelProfiles,
    retry: false,
  })

  const slotsQuery = useQuery<ProgramSlot[], Error>({
    queryKey: ['programlog-slots', channelId],
    queryFn: () => listProgramSlots(channelId),
    retry: false,
  })

  const logQuery = useQuery<ChannelLogEntry[], Error>({
    queryKey: ['programlog-log', channelId],
    queryFn: () => getChannelProgramLog(channelId, LOG_HOURS),
    retry: false,
  })

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['programlog-slots', channelId] })
    void queryClient.invalidateQueries({ queryKey: ['programlog-log', channelId] })
  }

  const materializeMutation = useMutation<MaterializeResult, Error>({
    mutationFn: materializeProgramLog,
    onSuccess: (result) => {
      refreshAll()
      toast.push({
        tone: 'success',
        message: 'Guide refreshed.',
        detail: `${result.scheduled} scheduled · ${result.skipped_conflict} conflicts · ${result.skipped_asset} not playable`,
      })
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : undefined
      toast.push({
        tone: 'error',
        message: 'Could not refresh the guide.',
        detail: detail ?? err.message,
      })
    },
  })

  const disableMutation = useMutation<SlotOccurrence[], Error, ProgramSlot>({
    mutationFn: (slot) => disableProgramSlot(slot.slot_id),
    onSuccess: (cancelled, slot) => {
      refreshAll()
      toast.push({
        tone: 'success',
        message: 'Slot disabled.',
        detail: `${slot.title_override?.trim() || slot.asset_id} · ${cancelled.length} future airing${cancelled.length === 1 ? '' : 's'} cancelled`,
      })
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : undefined
      toast.push({
        tone: 'error',
        message: 'Could not disable the slot.',
        detail: detail ?? err.message,
      })
    },
  })

  const channels = channelsQuery.data ?? []
  const slots = slotsQuery.data ?? []
  const entries = logQuery.data ?? []

  return (
    <div className="flex flex-col">
      <header className="px-6 pb-4 pt-6">
        <div
          className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: 'var(--cc-ink-3)' }}
        >
          Workflow
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Program guide</h1>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Place recordings on a channel&apos;s recurring guide. The automation
          engine airs scheduled entries and falls back to filler between
          programs. Times shown in your browser timezone.
        </p>
      </header>

      <div
        className="flex flex-wrap items-center gap-3 px-6 py-3"
        style={{ borderBottom: '1px solid var(--cc-line)' }}
      >
        <label className="flex items-center gap-2 text-xs">
          <span
            className="text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            Channel
          </span>
          <select
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="rounded-md px-3 py-1.5 text-xs"
            style={{
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          >
            {channels.length === 0 && <option value={channelId}>{channelId}</option>}
            {channels.map((c) => (
              <option key={c.channel_id} value={c.channel_id}>
                {c.branding?.display_name ?? c.channel_id}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => materializeMutation.mutate()}
          disabled={materializeMutation.isPending}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink-2)',
            background: 'var(--cc-surface)',
          }}
        >
          {materializeMutation.isPending ? 'Refreshing…' : 'Refresh guide'}
        </button>

        <div className="ml-auto">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            Add to guide
          </button>
        </div>
      </div>

      {(slotsQuery.isLoading || logQuery.isLoading) && (
        <div className="mx-6 my-6 flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-16 w-full animate-pulse rounded-md"
              style={{ background: 'var(--cc-surface-2)' }}
            />
          ))}
        </div>
      )}

      {slotsQuery.isError && (
        <ErrorState error={slotsQuery.error} onRetry={() => slotsQuery.refetch()} />
      )}
      {!slotsQuery.isError && logQuery.isError && (
        <ErrorState error={logQuery.error} onRetry={() => logQuery.refetch()} />
      )}

      {slotsQuery.isSuccess && logQuery.isSuccess && (
        <div className="flex flex-col gap-6 px-6 py-4">
          <section aria-label="Recurring slots">
            <h2
              className="mb-2 text-xs font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Recurring slots
            </h2>
            <SlotList
              slots={slots}
              disabling={disableMutation.isPending}
              onDisable={(slot) => {
                const display = slot.title_override?.trim() || slot.asset_id
                setPendingConfirm({
                  title: `Disable "${display}"?`,
                  body: 'All future airings from this recurring slot are cancelled from the guide immediately. Past and in-progress airings are unaffected, but nothing new will schedule until the slot is re-enabled.',
                  confirmLabel: 'Disable slot',
                  run: () => disableMutation.mutate(slot),
                })
              }}
            />
          </section>

          <section aria-label="Upcoming guide">
            <h2
              className="mb-2 text-xs font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Next 7 days
            </h2>
            <LogList entries={entries} />
          </section>
        </div>
      )}

      {drawerOpen && (
        <ProgramSlotDrawer
          channelId={channelId}
          onClose={() => setDrawerOpen(false)}
          onCreated={(slot) => {
            setDrawerOpen(false)
            refreshAll()
            toast.push({
              tone: 'success',
              message: 'Added to guide.',
              detail: `${slot.title_override?.trim() || slot.asset_id} · ${RECURRENCE_LABEL[slot.recurrence]}`,
            })
          }}
        />
      )}

      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          tone={pendingConfirm.tone}
          onConfirm={() => {
            pendingConfirm.run()
            setPendingConfirm(null)
          }}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}
