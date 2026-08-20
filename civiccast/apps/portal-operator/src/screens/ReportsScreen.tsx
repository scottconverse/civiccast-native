// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S23 Operator console: Reports (as-run, shows, hours-by-category).
//
// Three tabs, one filter row (date range + optional channel). The Hours-by-
// Category tab adds a required custom-field key input — the server returns
// `field_not_found=true` for an unknown key (rather than a 404) so the screen
// can call that out visibly without breaking the round-trip.
//
// Role-gated: support_admin (read). Other roles see an access banner and the
// data queries never fire (see `enabled: canRead` below).

import { useCallback, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  ApiError,
  downloadReportsExport,
  getAsRunReport,
  getHoursByCategoryReport,
  getShowsReport,
  getStaffIdentity,
  listChannels,
} from '../api/client'
import type {
  AsRunReport,
  ChannelProfile,
  HoursByCategoryReport,
  ShowsReport,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import { fieldNotFoundBanner, formatHms, formatHours } from './reports-format'

// Spec §4: support_admin reads franchise-compliance reports.
const ROLES = ['support_admin']

type Tone = 'neutral' | 'warn' | 'info'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div
      role="alert"
      className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {children}
    </div>
  )
}

type TabId = 'shows' | 'as-run' | 'hours'
type DownloadFormat = 'csv' | 'xml'

const TAB_LABELS: Record<TabId, string> = {
  shows: 'Shows',
  'as-run': 'As-Run',
  hours: 'Hours by Category',
}

interface FilterState {
  /** ISO date-only "YYYY-MM-DD" — the input[type=date] format. */
  from: string
  to: string
  channel: string
  field: string
}

function defaultRange(): { from: string; to: string } {
  // Default = a SINGLE-DAY window (today → tomorrow) so deploy-day operators
  // do not see "a month of nothing" on first load (UX-2). NOTE: Date.UTC
  // normalises out-of-range month/day values — e.g. Date.UTC(2026, -1, 1)
  // yields 2025-12-01 — so the previous code's `getUTCMonth() - 1` was correct
  // by accident on Jan boundaries (UX-16). We keep the construction simple and
  // depend on the same normalisation for the tomorrow rollover.
  const now = new Date()
  const fromDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
  const toDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1))
  return {
    from: fromDay.toISOString().slice(0, 10),
    to: toDay.toISOString().slice(0, 10),
  }
}

/**
 * Convert a `<input type=date>` value (YYYY-MM-DD) into an ISO timestamp the
 * server's `from`/`to` query params accept. The server treats the range as
 * half-open; we pass midnight UTC on both sides.
 */
function dateInputToIso(d: string): string {
  return d.length === 10 ? `${d}T00:00:00Z` : d
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function FilterBar({
  state,
  showField,
  rangeOk,
  rangeMessageId,
  channels,
  channelsUnavailable,
  onChange,
}: {
  state: FilterState
  showField: boolean
  rangeOk: boolean
  rangeMessageId: string
  channels: ChannelProfile[]
  channelsUnavailable: boolean
  onChange: (next: FilterState) => void
}) {
  const fromId = useId()
  const toId = useId()
  const chId = useId()
  const fldId = useId()
  const inputStyle = {
    background: 'var(--cc-surface)',
    border: '1px solid var(--cc-line)',
    color: 'var(--cc-ink)',
  }
  return (
    <section
      aria-label="Report filters"
      className="grid gap-3 rounded-md p-3 text-xs sm:grid-cols-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <label htmlFor={fromId} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>From</span>
        <input
          id={fromId}
          aria-label="From date (UTC)"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.from}
          onChange={(e) => onChange({ ...state, from: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={inputStyle}
        />
      </label>
      <label htmlFor={toId} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Through</span>
        <input
          id={toId}
          aria-label="Through date (UTC)"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.to}
          onChange={(e) => onChange({ ...state, to: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={inputStyle}
        />
        {!rangeOk && (
          <span
            id={rangeMessageId}
            role="alert"
            className="text-xs sm:col-span-2"
            style={{ color: 'var(--cc-warn)' }}
          >
            Pick a From date that is strictly before the Through date.
          </span>
        )}
      </label>
      <label htmlFor={chId} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Channel (optional)</span>
        {channelsUnavailable ? (
          <>
            <input
              id={chId}
              aria-label="Channel"
              type="text"
              value={state.channel}
              placeholder="any"
              onChange={(e) => onChange({ ...state, channel: e.target.value })}
              className="rounded-md px-2 py-1.5"
              style={inputStyle}
            />
            <span
              className="inline-block rounded px-1.5 py-0.5 text-[10px]"
              style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
            >
              Channel list unavailable; type the channel ID.
            </span>
          </>
        ) : (
          <select
            id={chId}
            aria-label="Channel"
            value={state.channel}
            onChange={(e) => onChange({ ...state, channel: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={inputStyle}
          >
            <option value="">All channels</option>
            {channels.map((c) => (
              <option key={c.channel_id} value={c.channel_id}>
                {c.slug ? `${c.slug} (${c.channel_id})` : c.channel_id}
              </option>
            ))}
          </select>
        )}
      </label>
      {showField && (
        <label htmlFor={fldId} className="grid gap-1">
          <span style={{ color: 'var(--cc-ink-3)' }}>Field key (required)</span>
          <input
            id={fldId}
            aria-label="Custom field key"
            type="text"
            value={state.field}
            placeholder="category"
            onChange={(e) => onChange({ ...state, field: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={inputStyle}
          />
        </label>
      )}
    </section>
  )
}

function DownloadLinks({
  type,
  state,
  disabled,
}: {
  type: 'as-run' | 'shows'
  state: FilterState
  disabled: boolean
}) {
  const from = dateInputToIso(state.from)
  const to = dateInputToIso(state.to)
  const channel = state.channel.trim() || undefined
  const field = type === 'as-run' && state.field.trim() ? state.field.trim() : undefined
  const [pendingFormat, setPendingFormat] = useState<DownloadFormat | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  // Mirror the disabled style of the table buttons so an empty range visibly
  // can't be downloaded (the server would 422; we surface the cause earlier).
  const style: React.CSSProperties = {
    background: 'var(--cc-surface)',
    border: '1px solid var(--cc-line)',
    color: 'var(--cc-ink)',
    opacity: disabled ? 0.4 : 1,
  }
  async function onDownload(format: DownloadFormat) {
    if (disabled || pendingFormat) return
    setDownloadError(null)
    setPendingFormat(format)
    try {
      const blob = await downloadReportsExport({ type, format, from, to, channel, field })
      saveBlob(blob, `civiccast-${type}-${from.slice(0, 10)}.${format}`)
    } catch (err) {
      setDownloadError(apiMessage(err, 'Could not download the report.'))
    } finally {
      setPendingFormat(null)
    }
  }
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || pendingFormat != null}
          aria-label={`Download ${type} CSV`}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={style}
          onClick={() => void onDownload('csv')}
        >
          {pendingFormat === 'csv' ? 'Downloading CSV...' : 'Download CSV'}
        </button>
        <button
          type="button"
          disabled={disabled || pendingFormat != null}
          aria-label={`Download ${type} XML`}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={style}
          onClick={() => void onDownload('xml')}
        >
          {pendingFormat === 'xml' ? 'Downloading XML...' : 'Download XML'}
        </button>
      </div>
      {downloadError && <Banner tone="warn">{downloadError}</Banner>}
    </div>
  )
}

const TAB_IDS: TabId[] = ['shows', 'as-run', 'hours']

function TabNav({ value, onChange }: { value: TabId; onChange: (id: TabId) => void }) {
  const refs = useRef<Record<TabId, HTMLButtonElement | null>>({
    shows: null,
    'as-run': null,
    hours: null,
  })

  const focusTab = useCallback((id: TabId) => {
    const el = refs.current[id]
    if (el) {
      el.focus()
    }
  }, [])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      const currentIdx = TAB_IDS.indexOf(value)
      if (currentIdx < 0) return
      let nextIdx: number | null = null
      if (e.key === 'ArrowRight') nextIdx = (currentIdx + 1) % TAB_IDS.length
      else if (e.key === 'ArrowLeft') nextIdx = (currentIdx - 1 + TAB_IDS.length) % TAB_IDS.length
      else if (e.key === 'Home') nextIdx = 0
      else if (e.key === 'End') nextIdx = TAB_IDS.length - 1
      if (nextIdx == null) return
      e.preventDefault()
      const nextId = TAB_IDS[nextIdx]
      onChange(nextId)
      focusTab(nextId)
    },
    [value, onChange, focusTab],
  )

  return (
    <div
      role="tablist"
      aria-label="Report kind"
      className="flex flex-wrap gap-1"
      onKeyDown={handleKeyDown}
    >
      {TAB_IDS.map((id) => {
        const active = id === value
        return (
          <button
            key={id}
            ref={(el) => {
              refs.current[id] = el
            }}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={active}
            aria-controls={`panel-${id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(id)}
            className="rounded-md px-3 py-1.5 text-sm font-medium"
            style={{
              background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
              color: active ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
              border: '1px solid var(--cc-line)',
            }}
          >
            {TAB_LABELS[id]}
          </button>
        )
      })}
    </div>
  )
}

// --- Per-tab tables ---------------------------------------------------------

function ShowsTable({ rows }: { rows: ShowsReport['rows'] }) {
  if (!rows || rows.length === 0) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        No air times in the selected range. As-run rows appear automatically when a meeting plays
        out — schedule a meeting under Run Meeting → Schedule, then run it. (Wider date ranges may
        surface earlier broadcasts if you already have history.)
      </p>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm" aria-label="Shows report">
        <thead>
          <tr style={{ color: 'var(--cc-ink-3)' }}>
            <th className="px-2 py-1 text-left">Asset</th>
            <th className="px-2 py-1 text-right">Plays</th>
            <th className="px-2 py-1 text-right">Total airtime</th>
            <th className="px-2 py-1 text-left">First aired (UTC)</th>
            <th className="px-2 py-1 text-left">Last aired (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.asset_id}
              style={{ borderTop: '1px solid var(--cc-line)' }}
            >
              <td className="cc-mono px-2 py-1 text-xs">{row.asset_id}</td>
              <td className="cc-tabular px-2 py-1 text-right">{row.play_count}</td>
              <td className="cc-tabular px-2 py-1 text-right">{formatHms(row.total_airtime_s)}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.first_aired}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.last_aired}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AsRunTable({ rows }: { rows: AsRunReport['rows'] }) {
  if (!rows || rows.length === 0) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        No as-run entries in the selected range. As-run rows appear automatically when a meeting
        plays out — schedule a meeting under Run Meeting → Schedule, then run it. (Wider date
        ranges may surface earlier broadcasts if you already have history.)
      </p>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm" aria-label="As-run report">
        <thead>
          <tr style={{ color: 'var(--cc-ink-3)' }}>
            <th className="px-2 py-1 text-left">Channel</th>
            <th className="px-2 py-1 text-left">Start (UTC)</th>
            <th className="px-2 py-1 text-left">End (UTC)</th>
            <th className="px-2 py-1 text-right">Duration</th>
            <th className="px-2 py-1 text-left">Source</th>
            <th className="px-2 py-1 text-left">Asset</th>
            <th className="px-2 py-1 text-left">Category</th>
            <th className="px-2 py-1 text-left">Verified</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.entry.entry_id}
              style={{ borderTop: '1px solid var(--cc-line)' }}
            >
              <td className="cc-mono px-2 py-1 text-xs">{row.entry.channel_id}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.entry.actual_start}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.entry.actual_end}</td>
              <td className="cc-tabular px-2 py-1 text-right">{formatHms(row.entry.duration_s)}</td>
              <td className="px-2 py-1 text-xs">{row.entry.source_kind}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.entry.asset_id ?? ''}</td>
              <td className="px-2 py-1 text-xs">{row.category ?? ''}</td>
              <td className="px-2 py-1 text-xs">
                {row.entry.verified ? 'yes' : 'no'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HoursTable({ report }: { report: HoursByCategoryReport }) {
  const rows = report.rows ?? []
  if (rows.length === 0) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        No entries grouped by &ldquo;{report.field_key}&rdquo; in the selected range.
      </p>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm" aria-label="Hours by category report">
        <thead>
          <tr style={{ color: 'var(--cc-ink-3)' }}>
            <th className="px-2 py-1 text-left">Category</th>
            <th className="px-2 py-1 text-right">Entries</th>
            <th className="px-2 py-1 text-right">Total airtime</th>
            <th className="px-2 py-1 text-right">Hours</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.category} style={{ borderTop: '1px solid var(--cc-line)' }}>
              <td className="px-2 py-1">{row.category}</td>
              <td className="cc-tabular px-2 py-1 text-right">{row.entry_count}</td>
              <td className="cc-tabular px-2 py-1 text-right">{formatHms(row.total_seconds)}</td>
              <td className="cc-tabular px-2 py-1 text-right">{formatHours(row.total_hours)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- Screen ----------------------------------------------------------------

export function ReportsScreen() {
  const rangeMessageId = useId()
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, ROLES)

  const [tab, setTab] = useState<TabId>('shows')
  const defaults = defaultRange()
  const [filters, setFilters] = useState<FilterState>({
    from: defaults.from,
    to: defaults.to,
    channel: '',
    field: 'category',
  })

  const fromIso = dateInputToIso(filters.from)
  const toIso = dateInputToIso(filters.to)
  const channel = filters.channel.trim() || undefined
  const field = filters.field.trim() || undefined
  const rangeOk = filters.from.length === 10 && filters.to.length === 10 && filters.from < filters.to

  // UX-5: load the canonical channel list once for the filter dropdown. If it
  // fails (server unavailable / permissions), the FilterBar falls back to a
  // free-text input so the operator is never stuck.
  const channelsQuery = useQuery<ChannelProfile[]>({
    queryKey: ['reports', 'channels'],
    queryFn: listChannels,
    enabled: canRead,
    retry: false,
  })
  const channels = channelsQuery.data ?? []
  const channelsUnavailable = channelsQuery.isError

  // UX-2: shows + as-run queries are NOT gated on the active tab. Both fire as
  // long as the role + range are valid so the deploy-day banner ("no content
  // has aired yet") can detect the empty-on-day-one case regardless of which
  // tab the operator landed on. The data is small (per-station aggregate
  // reports) and the role gate is enforced server-side.
  const showsQuery = useQuery<ShowsReport>({
    queryKey: ['reports', 'shows', fromIso, toIso, channel ?? null],
    queryFn: () => getShowsReport({ from: fromIso, to: toIso, channel }),
    enabled: canRead && rangeOk,
  })
  const asRunQuery = useQuery<AsRunReport>({
    queryKey: ['reports', 'as-run', fromIso, toIso, channel ?? null, field ?? null],
    queryFn: () => getAsRunReport({ from: fromIso, to: toIso, channel, field }),
    enabled: canRead && rangeOk,
  })
  const hoursQuery = useQuery<HoursByCategoryReport>({
    queryKey: ['reports', 'hours', fromIso, toIso, channel ?? null, field ?? null],
    queryFn: () =>
      getHoursByCategoryReport({ from: fromIso, to: toIso, channel, field: field ?? '' }),
    // Hours-by-category requires a non-empty field_key — the server 422s otherwise.
    enabled: canRead && tab === 'hours' && rangeOk && Boolean(field),
  })

  // UX-2: detect the "deploy-day" empty state. When the range is valid AND both
  // the Shows and As-Run queries have completed AND both came back with no rows
  // AND there is no field_not_found on Hours, we surface a friendlier banner so
  // a new operator sees "no data yet" rather than "looks broken."
  const showsReturnedZero =
    showsQuery.isSuccess && (showsQuery.data?.rows?.length ?? 0) === 0
  const asRunReturnedZero =
    asRunQuery.isSuccess && (asRunQuery.data?.rows?.length ?? 0) === 0
  const hoursIsFieldNotFound = hoursQuery.data?.field_not_found === true
  const deployDayBanner =
    rangeOk && showsReturnedZero && asRunReturnedZero && !hoursIsFieldNotFound

  if (identityQuery.isLoading) {
    return (
      <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        Loading…
      </div>
    )
  }
  if (identityQuery.isError) {
    return (
      <div className="px-6 py-10">
        <Banner tone="warn">
          Could not load your staff identity (
          {apiMessage(identityQuery.error, 'request failed')}). Check that you are signed in (staff
          token) and the local API is running, then retry.
        </Banner>
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Reports require the support admin role. Ask your station admin for access.
        </Banner>
      </div>
    )
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Reports</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Franchise-compliance reports off the as-run log. The date range is half-open
          ({'[from, to)'}) so a single day = From today, Through tomorrow. CSV/XML downloads use
          the same filter set as the on-screen table. Dates are UTC midnight to UTC midnight; if
          your station runs on local time, factor the offset into the From / Through you pick.
        </p>
      </div>

      {deployDayBanner && (
        <Banner tone="info">
          No content has aired yet on this station. Reports will populate after your first
          scheduled meeting plays out.
        </Banner>
      )}

      <TabNav value={tab} onChange={setTab} />
      <FilterBar
        state={filters}
        showField={tab !== 'shows'}
        rangeOk={rangeOk}
        rangeMessageId={rangeMessageId}
        channels={channels}
        channelsUnavailable={channelsUnavailable}
        onChange={setFilters}
      />

      {!rangeOk && (
        <Banner tone="warn">Pick a From date that is strictly before the Through date.</Banner>
      )}

      <section
        id="panel-shows"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-shows"
        aria-label="Shows report"
        hidden={tab !== 'shows'}
        className="space-y-3"
      >
        {tab === 'shows' && (
          <>
            <DownloadLinks type="shows" state={filters} disabled={!rangeOk} />
            {showsQuery.isLoading && (
              <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Loading shows report…
              </p>
            )}
            {showsQuery.isError && (
              <Banner tone="warn">
                {apiMessage(showsQuery.error, 'Could not load the shows report.')}
              </Banner>
            )}
            {showsQuery.data && <ShowsTable rows={showsQuery.data.rows} />}
          </>
        )}
      </section>

      <section
        id="panel-as-run"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-as-run"
        aria-label="As-run report"
        hidden={tab !== 'as-run'}
        className="space-y-3"
      >
        {tab === 'as-run' && (
          <>
            <DownloadLinks type="as-run" state={filters} disabled={!rangeOk} />
            {asRunQuery.isLoading && (
              <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Loading as-run report…
              </p>
            )}
            {asRunQuery.isError && (
              <Banner tone="warn">
                {apiMessage(asRunQuery.error, 'Could not load the as-run report.')}
              </Banner>
            )}
            {asRunQuery.data && <AsRunTable rows={asRunQuery.data.rows} />}
          </>
        )}
      </section>

      <section
        id="panel-hours"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-hours"
        aria-label="Hours by category report"
        hidden={tab !== 'hours'}
        className="space-y-3"
      >
        {tab === 'hours' && (
          <>
            {!field && (
              <Banner tone="info">
                Enter the custom-field key to group by (e.g. <code>category</code>).
              </Banner>
            )}
            {hoursQuery.isLoading && (
              <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Loading hours-by-category report…
              </p>
            )}
            {hoursQuery.isError && (
              <Banner tone="warn">
                {apiMessage(hoursQuery.error, 'Could not load the hours-by-category report.')}
              </Banner>
            )}
            {hoursQuery.data?.field_not_found && (
              <Banner tone="warn">{fieldNotFoundBanner(hoursQuery.data.field_key)}</Banner>
            )}
            {hoursQuery.data && !hoursQuery.data.field_not_found && (
              <HoursTable report={hoursQuery.data} />
            )}
          </>
        )}
      </section>
    </div>
  )
}
