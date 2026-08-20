// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S24 Operator console: Underwriting / sponsorship-spot management.
//
// Four tabs over one screen:
//   * Spots       — list + create/edit/delete with the 47 CFR 73.503 attest
//   * Flights     — list + create/edit/delete; date window + frequency cap
//   * Placements  — read-only view (the trafficking compiler writes these)
//   * Affidavits  — per-underwriter proof-of-airing + CSV/XML/PDF downloads
//
// Role gates:
//   * Spots / Flights / Placements → publish_operator OR setup_admin
//   * Affidavits                   → support_admin
// An operator with a mixed role set (e.g. publish_operator only) sees an
// access banner inside the tabs they can't read, NOT the whole-screen banner.
// A user with neither role family sees the whole-screen access banner.
//
// The FCC 47 CFR 73.503 reminder text is rendered VERBATIM under the
// `fcc_compliant_ack` checkbox on the spot form (spec DC-5). The route does
// NOT police content — the editorial attestation is the gate.

import {
  useCallback,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  affidavitExportUrl,
  createSpotFlight,
  createUnderwritingSpot,
  deleteSpotFlight,
  deleteUnderwritingSpot,
  getStaffIdentity,
  getUnderwriterAffidavit,
  listSpotFlights,
  listSpotPlacements,
  listUnderwritingSpots,
  patchSpotFlight,
  patchUnderwritingSpot,
} from '../api/client'
import type {
  SpotFlight,
  SpotFlightInput,
  SpotFlightUpdate,
  SpotPlacement,
  StaffIdentityResponse,
  UnderwriterAffidavit,
  UnderwritingSpot,
  UnderwritingSpotInput,
  UnderwritingSpotUpdate,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import {
  FCC_73_503_REMINDER,
  formatDuration,
  parseChannelsText,
  stringifyChannels,
} from './underwriting-format'

const MANAGE_ROLES = ['publish_operator', 'setup_admin']
const AFFIDAVIT_ROLES = ['support_admin']
const ALL_ROLES = [...MANAGE_ROLES, ...AFFIDAVIT_ROLES]
const DEFAULT_STATION_ID = 'civiccast-station'

type Tone = 'neutral' | 'warn' | 'info' | 'ok'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
}

const INPUT_STYLE: CSSProperties = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  // Only `warn` is an urgent / error condition — use `role="alert"` (assertive
  // live region) for that. Informational/neutral/ok banners use `role="status"`
  // (polite live region) so screen readers don't interrupt for routine info
  // (UX-8).
  const role = tone === 'warn' ? 'alert' : 'status'
  return (
    <div
      role={role}
      className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {children}
    </div>
  )
}

// --- Tabs ------------------------------------------------------------------

type TabId = 'spots' | 'flights' | 'placements' | 'affidavits'

const TAB_LABELS: Record<TabId, string> = {
  spots: 'Spots',
  flights: 'Flights',
  placements: 'Placements',
  affidavits: 'Affidavits',
}

const TAB_IDS: TabId[] = ['spots', 'flights', 'placements', 'affidavits']

function TabNav({ value, onChange }: { value: TabId; onChange: (id: TabId) => void }) {
  const refs = useRef<Record<TabId, HTMLButtonElement | null>>({
    spots: null,
    flights: null,
    placements: null,
    affidavits: null,
  })

  const focusTab = useCallback((id: TabId) => {
    const el = refs.current[id]
    if (el) el.focus()
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
      aria-label="Underwriting section"
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

// --- Spot form -------------------------------------------------------------

interface SpotFormState {
  /** null when creating; spot_id otherwise. */
  editingSpotId: string | null
  spot_id: string
  underwriter: string
  asset_id: string
  fcc_compliant_ack: boolean
  review_notes: string
}

const EMPTY_SPOT_FORM: SpotFormState = {
  editingSpotId: null,
  spot_id: '',
  underwriter: '',
  asset_id: '',
  fcc_compliant_ack: false,
  review_notes: '',
}

function formFromSpot(spot: UnderwritingSpot): SpotFormState {
  return {
    editingSpotId: spot.spot_id,
    spot_id: spot.spot_id,
    underwriter: spot.underwriter,
    asset_id: spot.asset_id,
    fcc_compliant_ack: spot.fcc_compliant_ack ?? false,
    review_notes: spot.review_notes ?? '',
  }
}

function SpotForm({
  form,
  onChange,
  onSubmit,
  onCancelEdit,
  pending,
}: {
  form: SpotFormState
  onChange: (next: SpotFormState) => void
  onSubmit: () => void
  onCancelEdit: () => void
  pending: boolean
}) {
  const idSpot = useId()
  const idUw = useId()
  const idAsset = useId()
  const idAck = useId()
  const idNotes = useId()
  const editing = form.editingSpotId != null
  const canSubmit =
    form.spot_id.trim().length > 0 &&
    form.underwriter.trim().length > 0 &&
    form.asset_id.trim().length > 0 &&
    !pending

  return (
    <section
      aria-label={editing ? 'Edit underwriting spot' : 'Create underwriting spot'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">
        {editing ? 'Edit spot' : 'Create spot'}
      </h2>

      <label htmlFor={idSpot} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Spot ID</span>
        <input
          id={idSpot}
          aria-label="Spot ID"
          type="text"
          value={form.spot_id}
          disabled={editing}
          placeholder="acme-15s-2026q3"
          onChange={(e) => onChange({ ...form, spot_id: e.target.value })}
          className="rounded-md px-2 py-1.5 disabled:opacity-60"
          style={INPUT_STYLE}
        />
      </label>

      <label htmlFor={idUw} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Underwriter</span>
        <input
          id={idUw}
          aria-label="Underwriter"
          type="text"
          value={form.underwriter}
          placeholder="Acme Co-op"
          onChange={(e) => onChange({ ...form, underwriter: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>

      <label htmlFor={idAsset} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Asset ID (the :15 / :30 acknowledgment video)</span>
        <input
          id={idAsset}
          aria-label="Asset ID"
          type="text"
          value={form.asset_id}
          placeholder="asset-acme-ack-2026q3"
          onChange={(e) => onChange({ ...form, asset_id: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>

      <div className="space-y-1.5">
        <label htmlFor={idAck} className="flex items-start gap-2 text-xs">
          <input
            id={idAck}
            aria-label="FCC 47 CFR 73.503 attestation"
            aria-describedby={`${idAck}-help`}
            type="checkbox"
            checked={form.fcc_compliant_ack}
            onChange={(e) => onChange({ ...form, fcc_compliant_ack: e.target.checked })}
            className="mt-0.5"
          />
          <span>
            I attest this spot meets <strong>47 CFR 73.503</strong>.
          </span>
        </label>
        <p
          id={`${idAck}-help`}
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-info-soft)', border: '1px solid var(--cc-info)' }}
        >
          {FCC_73_503_REMINDER}
        </p>
      </div>

      <label htmlFor={idNotes} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Review notes (optional)</span>
        <textarea
          id={idNotes}
          aria-label="Review notes"
          rows={3}
          value={form.review_notes}
          placeholder="What you checked; any caveats; reviewer initials + date."
          onChange={(e) => onChange({ ...form, review_notes: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {editing ? 'Save changes' : 'Create spot'}
        </button>
        {editing && (
          <button
            type="button"
            onClick={onCancelEdit}
            className="rounded-md px-3 py-1.5 font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Cancel
          </button>
        )}
      </div>
    </section>
  )
}

// --- Spot list -------------------------------------------------------------

function SpotRow({
  spot,
  onEdit,
  onArmDelete,
  onConfirmDelete,
  confirming,
  deleting,
}: {
  spot: UnderwritingSpot
  onEdit: () => void
  onArmDelete: () => void
  onConfirmDelete: () => void
  confirming: boolean
  deleting: boolean
}) {
  return (
    <li
      className="space-y-2 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <strong>{spot.spot_id}</strong>{' '}
          <span className="cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            uw={spot.underwriter} · asset={spot.asset_id}
          </span>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {spot.fcc_compliant_ack
              ? 'FCC 73.503 attested.'
              : 'NOT attested — operator must attest before traffic.'}
          </div>
          {spot.review_notes && (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Notes: {spot.review_notes}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            aria-label={`Edit ${spot.spot_id}`}
            onClick={onEdit}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Edit
          </button>
          {confirming ? (
            <button
              type="button"
              aria-label={`Confirm delete ${spot.spot_id}`}
              disabled={deleting}
              onClick={onConfirmDelete}
              className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              {deleting ? 'Deleting…' : 'Confirm delete'}
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Delete ${spot.spot_id}`}
              onClick={onArmDelete}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {confirming && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Confirming will also delete every flight + placement that referenced this spot.
        </p>
      )}
    </li>
  )
}

// --- Flight form -----------------------------------------------------------

interface FlightFormState {
  editingFlightId: string | null
  flight_id: string
  spot_id: string
  start_date: string
  end_date: string
  frequency_cap_per_day: string
  daypart_block_id: string
  channels_text: string
}

const EMPTY_FLIGHT_FORM: FlightFormState = {
  editingFlightId: null,
  flight_id: '',
  spot_id: '',
  start_date: '',
  end_date: '',
  frequency_cap_per_day: '',
  daypart_block_id: '',
  channels_text: '',
}

function formFromFlight(flight: SpotFlight): FlightFormState {
  return {
    editingFlightId: flight.flight_id,
    flight_id: flight.flight_id,
    spot_id: flight.spot_id,
    start_date: flight.start_date,
    end_date: flight.end_date,
    frequency_cap_per_day:
      flight.frequency_cap_per_day == null ? '' : String(flight.frequency_cap_per_day),
    daypart_block_id: flight.daypart_block_id ?? '',
    channels_text: stringifyChannels(flight.channels),
  }
}

function parseFreqCap(text: string): { ok: boolean; value: number | null } {
  const trimmed = text.trim()
  if (trimmed.length === 0) return { ok: true, value: null }
  if (!/^\d+$/.test(trimmed)) return { ok: false, value: null }
  const n = Number.parseInt(trimmed, 10)
  if (!Number.isFinite(n) || n < 1 || n > 1440) return { ok: false, value: null }
  return { ok: true, value: n }
}

function FlightForm({
  form,
  onChange,
  onSubmit,
  onCancelEdit,
  pending,
  spots,
  spotsLoading,
}: {
  form: FlightFormState
  onChange: (next: FlightFormState) => void
  onSubmit: () => void
  onCancelEdit: () => void
  pending: boolean
  spots: UnderwritingSpot[]
  spotsLoading: boolean
}) {
  const idFlight = useId()
  const idSpot = useId()
  const idStart = useId()
  const idEnd = useId()
  const idCap = useId()
  const idDp = useId()
  const idCh = useId()
  const editing = form.editingFlightId != null
  const freqParsed = parseFreqCap(form.frequency_cap_per_day)
  const rangeOk =
    form.start_date.length === 10 &&
    form.end_date.length === 10 &&
    form.start_date <= form.end_date
  const canSubmit =
    form.flight_id.trim().length > 0 &&
    form.spot_id.trim().length > 0 &&
    rangeOk &&
    freqParsed.ok &&
    !pending

  return (
    <section
      aria-label={editing ? 'Edit spot flight' : 'Create spot flight'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">
        {editing ? 'Edit flight' : 'Create flight'}
      </h2>

      <label htmlFor={idFlight} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Flight ID</span>
        <input
          id={idFlight}
          aria-label="Flight ID"
          type="text"
          value={form.flight_id}
          disabled={editing}
          placeholder="acme-2026q3-pubgov"
          onChange={(e) => onChange({ ...form, flight_id: e.target.value })}
          className="rounded-md px-2 py-1.5 disabled:opacity-60"
          style={INPUT_STYLE}
        />
      </label>

      <label htmlFor={idSpot} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Spot</span>
        <select
          id={idSpot}
          aria-label="Spot"
          value={form.spot_id}
          disabled={editing}
          onChange={(e) => onChange({ ...form, spot_id: e.target.value })}
          className="rounded-md px-2 py-1.5 disabled:opacity-60"
          style={INPUT_STYLE}
        >
          <option value="">{spotsLoading ? 'Loading spots…' : 'Pick a spot…'}</option>
          {spots.map((s) => (
            <option key={s.spot_id} value={s.spot_id}>
              {s.spot_id} — {s.underwriter}
            </option>
          ))}
        </select>
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={idStart} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Start date</span>
          <input
            id={idStart}
            aria-label="Start date"
            type="date"
            value={form.start_date}
            onChange={(e) => onChange({ ...form, start_date: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
        <label htmlFor={idEnd} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>End date</span>
          <input
            id={idEnd}
            aria-label="End date"
            type="date"
            value={form.end_date}
            onChange={(e) => onChange({ ...form, end_date: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
      </div>
      {!rangeOk && (form.start_date || form.end_date) && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Start date must be on or before end date (inclusive window).
        </p>
      )}

      <label htmlFor={idCap} className="grid gap-1 text-xs" style={{ maxWidth: '12rem' }}>
        <span style={{ color: 'var(--cc-ink-3)' }}>Frequency cap (per day, optional)</span>
        <input
          id={idCap}
          aria-label="Frequency cap per day"
          type="number"
          inputMode="numeric"
          min={1}
          max={1440}
          value={form.frequency_cap_per_day}
          placeholder="e.g. 6"
          onChange={(e) => onChange({ ...form, frequency_cap_per_day: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
        {!freqParsed.ok && (
          <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
            Frequency cap must be a whole number 1–1440 (or blank).
          </span>
        )}
      </label>

      <label htmlFor={idDp} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Daypart block ID (optional)</span>
        <input
          id={idDp}
          aria-label="Daypart block ID"
          type="text"
          value={form.daypart_block_id}
          placeholder="prime-evening"
          onChange={(e) => onChange({ ...form, daypart_block_id: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
        <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Daypart block management is coming in a future release. For now, type the block ID
          you got from your scheduling team.
        </span>
      </label>

      <label htmlFor={idCh} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Channels (comma- or newline-separated)</span>
        <textarea
          id={idCh}
          aria-label="Channels"
          rows={2}
          value={form.channels_text}
          placeholder="pub-1, gov-1"
          onChange={(e) => onChange({ ...form, channels_text: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {editing ? 'Save changes' : 'Create flight'}
        </button>
        {editing && (
          <button
            type="button"
            onClick={onCancelEdit}
            className="rounded-md px-3 py-1.5 font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Cancel
          </button>
        )}
      </div>
    </section>
  )
}

// --- Flight list -----------------------------------------------------------

function FlightRow({
  flight,
  onEdit,
  onArmDelete,
  onConfirmDelete,
  confirming,
  deleting,
}: {
  flight: SpotFlight
  onEdit: () => void
  onArmDelete: () => void
  onConfirmDelete: () => void
  confirming: boolean
  deleting: boolean
}) {
  return (
    <li
      className="space-y-2 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <strong>{flight.flight_id}</strong>{' '}
          <span className="cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            spot={flight.spot_id} · {flight.start_date} → {flight.end_date}
          </span>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            cap={flight.frequency_cap_per_day ?? '—'}/day · daypart=
            {flight.daypart_block_id ?? '—'} · ch={stringifyChannels(flight.channels) || '—'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            aria-label={`Edit ${flight.flight_id}`}
            onClick={onEdit}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Edit
          </button>
          {confirming ? (
            <button
              type="button"
              aria-label={`Confirm delete ${flight.flight_id}`}
              disabled={deleting}
              onClick={onConfirmDelete}
              className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              {deleting ? 'Deleting…' : 'Confirm delete'}
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Delete ${flight.flight_id}`}
              onClick={onArmDelete}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {confirming && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Confirming will also delete every placement that referenced this flight.
        </p>
      )}
    </li>
  )
}

// --- Placements ------------------------------------------------------------

interface PlacementFilterState {
  /** YYYY-MM-DD */
  from: string
  to: string
  channel: string
  flight: string
}

function defaultDayRange(): { from: string; to: string } {
  const now = new Date()
  const fromDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
  const toDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1))
  return {
    from: fromDay.toISOString().slice(0, 10),
    to: toDay.toISOString().slice(0, 10),
  }
}

function dateInputToIso(d: string): string {
  return d.length === 10 ? `${d}T00:00:00Z` : d
}

function PlacementFilters({
  state,
  rangeOk,
  rangeMessageId,
  onChange,
}: {
  state: PlacementFilterState
  rangeOk: boolean
  rangeMessageId: string
  onChange: (next: PlacementFilterState) => void
}) {
  const idFrom = useId()
  const idTo = useId()
  const idCh = useId()
  const idFl = useId()
  return (
    <section
      aria-label="Placement filters"
      className="grid gap-3 rounded-md p-3 text-xs sm:grid-cols-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <label htmlFor={idFrom} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>From</span>
        <input
          id={idFrom}
          aria-label="From date (UTC)"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.from}
          onChange={(e) => onChange({ ...state, from: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idTo} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Through</span>
        <input
          id={idTo}
          aria-label="Through date (UTC)"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.to}
          onChange={(e) => onChange({ ...state, to: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idCh} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Channel (optional)</span>
        <input
          id={idCh}
          aria-label="Channel"
          type="text"
          value={state.channel}
          placeholder="any"
          onChange={(e) => onChange({ ...state, channel: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idFl} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Flight (optional)</span>
        <input
          id={idFl}
          aria-label="Flight"
          type="text"
          value={state.flight}
          placeholder="any"
          onChange={(e) => onChange({ ...state, flight: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
    </section>
  )
}

function PlacementsTable({ rows }: { rows: SpotPlacement[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        No placements in the selected window. Placements are materialized by the trafficking
        compiler; they will appear here automatically once a flight is in range and the compiler
        runs.
      </p>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm" aria-label="Spot placements">
        <thead>
          <tr style={{ color: 'var(--cc-ink-3)' }}>
            <th className="px-2 py-1 text-left">Scheduled (UTC)</th>
            <th className="px-2 py-1 text-left">Channel</th>
            <th className="px-2 py-1 text-left">Flight</th>
            <th className="px-2 py-1 text-left">Schedule item</th>
            <th className="px-2 py-1 text-left">Placement</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.placement_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
              <td className="cc-mono px-2 py-1 text-xs">{row.scheduled_at}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.channel_id}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.flight_id}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.schedule_item_id}</td>
              <td className="cc-mono px-2 py-1 text-xs">{row.placement_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- Affidavits ------------------------------------------------------------

interface AffidavitFilterState {
  underwriter: string
  /** YYYY-MM-DD; inclusive both sides per spec. */
  from: string
  to: string
}

function defaultMonthRange(): { from: string; to: string } {
  const now = new Date()
  const first = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1))
  const last = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0))
  return {
    from: first.toISOString().slice(0, 10),
    to: last.toISOString().slice(0, 10),
  }
}

function AffidavitFilters({
  state,
  rangeOk,
  rangeMessageId,
  onChange,
}: {
  state: AffidavitFilterState
  rangeOk: boolean
  rangeMessageId: string
  onChange: (next: AffidavitFilterState) => void
}) {
  const idUw = useId()
  const idFrom = useId()
  const idTo = useId()
  // UX-5: vocabulary now "From" / "Through" (no "(inclusive)" parenthetical —
  // the half-open vs inclusive distinction lives in the under-H1 lede). aria-
  // labels are synced to the visible labels (was "Period start" / "Period
  // end").
  // UX-3: aria-describedby + aria-invalid on the From/Through date inputs
  // mirrors PlacementFilters so the inline range warning is announced to AT.
  return (
    <section
      aria-label="Affidavit filters"
      className="grid gap-3 rounded-md p-3 text-xs sm:grid-cols-3"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <label htmlFor={idUw} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Underwriter (exact match)</span>
        <input
          id={idUw}
          aria-label="Underwriter"
          type="text"
          value={state.underwriter}
          placeholder="Acme Co-op"
          onChange={(e) => onChange({ ...state, underwriter: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idFrom} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>From</span>
        <input
          id={idFrom}
          aria-label="From date"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.from}
          onChange={(e) => onChange({ ...state, from: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idTo} className="grid gap-1">
        <span style={{ color: 'var(--cc-ink-3)' }}>Through</span>
        <input
          id={idTo}
          aria-label="Through date"
          aria-describedby={!rangeOk ? rangeMessageId : undefined}
          aria-invalid={!rangeOk || undefined}
          type="date"
          value={state.to}
          onChange={(e) => onChange({ ...state, to: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
    </section>
  )
}

function AffidavitDownloadLinks({
  state,
  disabled,
}: {
  state: AffidavitFilterState
  disabled: boolean
}) {
  // UX-4: `pointer-events: none` is a CSS-only mouse-block — `<a href>`
  // remained tab-focusable + Enter-activatable. When disabled we now also
  // remove the link from the tab order (`tabIndex={-1}`), advertise the state
  // via `aria-disabled`, and short-circuit clicks/keypresses via the onClick
  // preventDefault. This protects keyboard users from firing 422-bound URLs.
  const linkStyle: CSSProperties = {
    background: 'var(--cc-surface)',
    border: '1px solid var(--cc-line)',
    color: 'var(--cc-ink)',
    opacity: disabled ? 0.4 : 1,
    pointerEvents: disabled ? 'none' : undefined,
  }
  const formats: Array<'csv' | 'xml' | 'pdf'> = ['csv', 'xml', 'pdf']
  return (
    <div className="flex flex-wrap gap-2">
      {formats.map((fmt) => {
        const href = affidavitExportUrl({
          underwriter: state.underwriter,
          from: state.from,
          to: state.to,
          format: fmt,
        })
        return (
          <a
            key={fmt}
            href={href}
            download
            aria-disabled={disabled || undefined}
            aria-label={`Download affidavit ${fmt.toUpperCase()}`}
            tabIndex={disabled ? -1 : undefined}
            onClick={
              disabled
                ? (e) => {
                    e.preventDefault()
                  }
                : undefined
            }
            className="rounded-md px-3 py-1.5 text-xs font-medium"
            style={linkStyle}
          >
            Download {fmt.toUpperCase()}
          </a>
        )
      })}
    </div>
  )
}

function AffidavitTable({ affidavit }: { affidavit: UnderwriterAffidavit }) {
  if (affidavit.aired.length === 0) {
    // UX-2: previously the zero-airings empty state read only "No spot airings
    // for X between Y and Z." which could mean three different things — a
    // misspelled underwriter, no spots defined yet, or a period with no
    // matching airings. Enumerate the three causes so a billing operator
    // knows what to check before re-running or mis-billing.
    return (
      <div
        role="status"
        className="space-y-1 rounded-md p-3 text-xs"
        style={{ background: 'var(--cc-info-soft)', border: '1px solid var(--cc-info)' }}
      >
        <p>
          No airings recorded for <strong>{affidavit.underwriter}</strong> between{' '}
          {affidavit.period_start} and {affidavit.period_end}.
        </p>
        <p style={{ color: 'var(--cc-ink-3)' }}>This could mean any of:</p>
        <ul className="ml-4 list-disc space-y-0.5" style={{ color: 'var(--cc-ink-3)' }}>
          <li>
            The underwriter name does not match a spot exactly — check spelling in the Spots
            tab (the match is case-sensitive and exact).
          </li>
          <li>
            The underwriter has spots but no flights, or no flights overlapping this period —
            check the Flights tab.
          </li>
          <li>
            Flights exist but no spots have aired yet in this window — either widen the date
            range or wait for scheduled spots to play out.
          </li>
        </ul>
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="overflow-auto">
        <table className="w-full text-sm" aria-label="Affidavit airings">
          <thead>
            <tr style={{ color: 'var(--cc-ink-3)' }}>
              <th className="px-2 py-1 text-left">Aired (UTC)</th>
              <th className="px-2 py-1 text-left">Channel</th>
              <th className="px-2 py-1 text-left">Spot</th>
              <th className="px-2 py-1 text-left">Asset</th>
              <th className="px-2 py-1 text-left">Placement</th>
              <th className="px-2 py-1 text-right">Duration</th>
            </tr>
          </thead>
          <tbody>
            {affidavit.aired.map((a, idx) => (
              <tr
                key={`${a.placement_id ?? 'noplacement'}-${idx}`}
                style={{ borderTop: '1px solid var(--cc-line)' }}
              >
                <td className="cc-mono px-2 py-1 text-xs">{a.aired_at}</td>
                <td className="cc-mono px-2 py-1 text-xs">{a.channel_id}</td>
                <td className="cc-mono px-2 py-1 text-xs">{a.spot_id}</td>
                <td className="cc-mono px-2 py-1 text-xs">{a.asset_id}</td>
                <td className="cc-mono px-2 py-1 text-xs">{a.placement_id ?? '—'}</td>
                <td className="cc-tabular px-2 py-1 text-right">{formatDuration(a.duration_s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Totals: <strong>{affidavit.total_airings}</strong> airing
        {affidavit.total_airings === 1 ? '' : 's'} ·{' '}
        <strong>{formatDuration(affidavit.total_seconds)}</strong> ({affidavit.total_seconds}s)
      </div>
    </div>
  )
}

// --- Screen ----------------------------------------------------------------

/**
 * Outer screen — handles identity loading + error + whole-screen role gate.
 * The four-tab body is mounted ONLY after identity resolves, so the body's
 * `useState(canManage ? 'spots' : 'affidavits')` initialiser runs with the
 * correct `canManage` value from the first render. Previously the state was
 * initialised at the outer mount BEFORE identity loaded — `canManage` was
 * `false`, so a publish_operator-only operator was stuck on the Affidavits
 * tab with the access-denied banner (UX-1).
 */
export function UnderwritingScreen() {
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })

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
  const canDoAnything = hasRole(identityQuery.data, ALL_ROLES)
  if (!canDoAnything) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Underwriting requires the publish operator, setup admin, or support admin role. Ask your
          station admin for access.
        </Banner>
      </div>
    )
  }
  // identityQuery.data is defined here — `canDoAnything` would have been
  // false otherwise.
  return <UnderwritingBody identity={identityQuery.data!} />
}

function UnderwritingBody({ identity }: { identity: StaffIdentityResponse }) {
  const qc = useQueryClient()
  const rangeMessageId = useId()
  const affidavitRangeMessageId = useId()

  const canManage = hasRole(identity, MANAGE_ROLES)
  const canReadAffidavits = hasRole(identity, AFFIDAVIT_ROLES)

  // Default tab — pick a tab the user can actually read so a support-admin-
  // only operator lands on Affidavits rather than the Spots access banner.
  // Identity is GUARANTEED loaded by the parent gate, so this initialiser
  // captures the correct `canManage` on the first render (UX-1).
  const initialTab: TabId = canManage ? 'spots' : 'affidavits'
  const [tab, setTab] = useState<TabId>(initialTab)

  // --- Spots state ---
  const [spotForm, setSpotForm] = useState<SpotFormState>(EMPTY_SPOT_FORM)
  const [spotConfirmDelete, setSpotConfirmDelete] = useState<Record<string, true>>({})
  const spotsQuery = useQuery({
    queryKey: ['underwriting-spots'],
    queryFn: () => listUnderwritingSpots(),
    enabled: canManage,
  })

  const invalidateSpots = () => qc.invalidateQueries({ queryKey: ['underwriting-spots'] })

  const createSpotMut = useMutation({
    mutationFn: (payload: UnderwritingSpotInput) => createUnderwritingSpot(payload),
    onSuccess: () => {
      invalidateSpots()
      setSpotForm(EMPTY_SPOT_FORM)
    },
  })
  const patchSpotMut = useMutation({
    mutationFn: (v: { spotId: string; patch: UnderwritingSpotUpdate }) =>
      patchUnderwritingSpot(v.spotId, v.patch),
    onSuccess: () => {
      invalidateSpots()
      setSpotForm(EMPTY_SPOT_FORM)
    },
  })
  const deleteSpotMut = useMutation({
    mutationFn: (spotId: string) => deleteUnderwritingSpot(spotId),
    onSuccess: (_data, spotId) => {
      setSpotConfirmDelete((prev) => {
        const next = { ...prev }
        delete next[spotId]
        return next
      })
      // A spot delete cascades to flights + placements, so blow away every
      // underwriting cache so the UI reflects the server's transactional cleanup.
      qc.invalidateQueries({ queryKey: ['underwriting-spots'] })
      qc.invalidateQueries({ queryKey: ['underwriting-flights'] })
      qc.invalidateQueries({ queryKey: ['underwriting-placements'] })
    },
  })

  const handleSubmitSpot = () => {
    if (spotForm.editingSpotId != null) {
      const patch: UnderwritingSpotUpdate = {
        underwriter: spotForm.underwriter.trim(),
        asset_id: spotForm.asset_id.trim(),
        fcc_compliant_ack: spotForm.fcc_compliant_ack,
        review_notes: spotForm.review_notes.trim() === '' ? null : spotForm.review_notes,
      }
      patchSpotMut.mutate({ spotId: spotForm.editingSpotId, patch })
      return
    }
    const payload: UnderwritingSpotInput = {
      spot_id: spotForm.spot_id.trim(),
      station_id: DEFAULT_STATION_ID,
      underwriter: spotForm.underwriter.trim(),
      asset_id: spotForm.asset_id.trim(),
      fcc_compliant_ack: spotForm.fcc_compliant_ack,
      review_notes: spotForm.review_notes.trim() === '' ? null : spotForm.review_notes,
    }
    createSpotMut.mutate(payload)
  }

  const sortedSpots = useMemo(() => {
    const list = spotsQuery.data ?? []
    return [...list].sort((a, b) => {
      const uw = a.underwriter.localeCompare(b.underwriter)
      if (uw !== 0) return uw
      return a.spot_id.localeCompare(b.spot_id)
    })
  }, [spotsQuery.data])

  // --- Flights state ---
  const [flightForm, setFlightForm] = useState<FlightFormState>(EMPTY_FLIGHT_FORM)
  const [flightConfirmDelete, setFlightConfirmDelete] = useState<Record<string, true>>({})
  const flightsQuery = useQuery({
    queryKey: ['underwriting-flights'],
    queryFn: () => listSpotFlights(),
    enabled: canManage,
  })

  const invalidateFlights = () => qc.invalidateQueries({ queryKey: ['underwriting-flights'] })

  const createFlightMut = useMutation({
    mutationFn: (payload: SpotFlightInput) => createSpotFlight(payload),
    onSuccess: () => {
      invalidateFlights()
      setFlightForm(EMPTY_FLIGHT_FORM)
    },
  })
  const patchFlightMut = useMutation({
    mutationFn: (v: { flightId: string; patch: SpotFlightUpdate }) =>
      patchSpotFlight(v.flightId, v.patch),
    onSuccess: () => {
      invalidateFlights()
      setFlightForm(EMPTY_FLIGHT_FORM)
    },
  })
  const deleteFlightMut = useMutation({
    mutationFn: (flightId: string) => deleteSpotFlight(flightId),
    onSuccess: (_data, flightId) => {
      setFlightConfirmDelete((prev) => {
        const next = { ...prev }
        delete next[flightId]
        return next
      })
      // Flight delete cascades to placements per server.
      qc.invalidateQueries({ queryKey: ['underwriting-flights'] })
      qc.invalidateQueries({ queryKey: ['underwriting-placements'] })
    },
  })

  const handleSubmitFlight = () => {
    const freq = parseFreqCap(flightForm.frequency_cap_per_day)
    if (!freq.ok) return
    const channels = parseChannelsText(flightForm.channels_text)
    const daypart =
      flightForm.daypart_block_id.trim() === '' ? null : flightForm.daypart_block_id.trim()
    if (flightForm.editingFlightId != null) {
      const patch: SpotFlightUpdate = {
        start_date: flightForm.start_date,
        end_date: flightForm.end_date,
        frequency_cap_per_day: freq.value,
        daypart_block_id: daypart,
        channels: channels.length === 0 ? null : channels,
      }
      patchFlightMut.mutate({ flightId: flightForm.editingFlightId, patch })
      return
    }
    const payload: SpotFlightInput = {
      flight_id: flightForm.flight_id.trim(),
      spot_id: flightForm.spot_id.trim(),
      start_date: flightForm.start_date,
      end_date: flightForm.end_date,
      frequency_cap_per_day: freq.value,
      daypart_block_id: daypart,
      channels,
    }
    createFlightMut.mutate(payload)
  }

  const sortedFlights = useMemo(() => {
    const list = flightsQuery.data ?? []
    return [...list].sort((a, b) => {
      const start = a.start_date.localeCompare(b.start_date)
      if (start !== 0) return start
      return a.flight_id.localeCompare(b.flight_id)
    })
  }, [flightsQuery.data])

  // --- Placements state ---
  const placementDefaults = defaultDayRange()
  const [placementFilters, setPlacementFilters] = useState<PlacementFilterState>({
    from: placementDefaults.from,
    to: placementDefaults.to,
    channel: '',
    flight: '',
  })
  const placementsRangeOk =
    placementFilters.from.length === 10 &&
    placementFilters.to.length === 10 &&
    placementFilters.from < placementFilters.to
  const placementsQuery = useQuery({
    queryKey: [
      'underwriting-placements',
      placementFilters.from,
      placementFilters.to,
      placementFilters.channel,
      placementFilters.flight,
    ],
    queryFn: () =>
      listSpotPlacements({
        from: dateInputToIso(placementFilters.from),
        to: dateInputToIso(placementFilters.to),
        channel: placementFilters.channel.trim() || undefined,
        flight: placementFilters.flight.trim() || undefined,
      }),
    enabled: canManage && tab === 'placements' && placementsRangeOk,
  })

  // --- Affidavit state ---
  const monthDefaults = defaultMonthRange()
  const [affidavitFilters, setAffidavitFilters] = useState<AffidavitFilterState>({
    underwriter: '',
    from: monthDefaults.from,
    to: monthDefaults.to,
  })
  const affidavitRangeOk =
    affidavitFilters.from.length === 10 &&
    affidavitFilters.to.length === 10 &&
    affidavitFilters.from <= affidavitFilters.to
  const affidavitReady =
    affidavitFilters.underwriter.trim().length > 0 && affidavitRangeOk
  const affidavitQuery = useQuery<UnderwriterAffidavit>({
    queryKey: [
      'underwriting-affidavit',
      affidavitFilters.underwriter,
      affidavitFilters.from,
      affidavitFilters.to,
    ],
    queryFn: () =>
      getUnderwriterAffidavit({
        underwriter: affidavitFilters.underwriter.trim(),
        from: affidavitFilters.from,
        to: affidavitFilters.to,
      }),
    enabled: canReadAffidavits && tab === 'affidavits' && affidavitReady,
  })

  const manageDeniedBanner = (
    <Banner tone="info">
      This tab requires the publish operator or setup admin role. Ask your station admin for
      access.
    </Banner>
  )
  const affidavitsDeniedBanner = (
    <Banner tone="info">
      Affidavits require the support admin role. Ask your station admin for access.
    </Banner>
  )

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Underwriting</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Manage sponsorship spots, schedule flights, see what the trafficking compiler placed,
          and export per-underwriter affidavits for billing. The 47 CFR 73.503 sponsor-ID
          boundary is enforced by your editorial attestation — content is not auto-checked.
        </p>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Date ranges: the Placements tab uses a half-open window
          (<code className="cc-mono">[From, Through)</code>) — for a single day, pick today as From
          and tomorrow as Through. The Affidavits tab includes both ends of the period.
        </p>
      </div>

      <TabNav value={tab} onChange={setTab} />

      <section
        id="panel-spots"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-spots"
        aria-label="Underwriting spots"
        hidden={tab !== 'spots'}
        className="space-y-3"
      >
        {tab === 'spots' &&
          (!canManage ? (
            manageDeniedBanner
          ) : (
            <>
              <SpotForm
                form={spotForm}
                onChange={setSpotForm}
                onSubmit={handleSubmitSpot}
                onCancelEdit={() => setSpotForm(EMPTY_SPOT_FORM)}
                pending={createSpotMut.isPending || patchSpotMut.isPending}
              />
              {createSpotMut.isError && (
                <Banner tone="warn">
                  {apiMessage(createSpotMut.error, 'Could not create the spot.')}
                </Banner>
              )}
              {patchSpotMut.isError && (
                <Banner tone="warn">
                  {apiMessage(patchSpotMut.error, 'Could not save the spot.')}
                </Banner>
              )}
              {deleteSpotMut.isError && (
                <Banner tone="warn">
                  {apiMessage(deleteSpotMut.error, 'Could not delete the spot.')}
                </Banner>
              )}
              <section aria-label="Underwriting spots list" className="space-y-2">
                <h2 className="text-sm font-semibold">Spots</h2>
                {spotsQuery.isLoading ? (
                  <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    Loading spots…
                  </p>
                ) : spotsQuery.isError ? (
                  <Banner tone="warn">
                    {apiMessage(spotsQuery.error, 'Could not load spots.')}
                  </Banner>
                ) : sortedSpots.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    No underwriting spots are defined yet. Use the form above to create one.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {sortedSpots.map((spot) => (
                      <SpotRow
                        key={spot.spot_id}
                        spot={spot}
                        onEdit={() => setSpotForm(formFromSpot(spot))}
                        onArmDelete={() =>
                          setSpotConfirmDelete((prev) => ({ ...prev, [spot.spot_id]: true }))
                        }
                        onConfirmDelete={() => deleteSpotMut.mutate(spot.spot_id)}
                        confirming={spot.spot_id in spotConfirmDelete}
                        deleting={
                          deleteSpotMut.isPending && deleteSpotMut.variables === spot.spot_id
                        }
                      />
                    ))}
                  </ul>
                )}
              </section>
            </>
          ))}
      </section>

      <section
        id="panel-flights"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-flights"
        aria-label="Spot flights"
        hidden={tab !== 'flights'}
        className="space-y-3"
      >
        {tab === 'flights' &&
          (!canManage ? (
            manageDeniedBanner
          ) : (
            <>
              <FlightForm
                form={flightForm}
                onChange={setFlightForm}
                onSubmit={handleSubmitFlight}
                onCancelEdit={() => setFlightForm(EMPTY_FLIGHT_FORM)}
                pending={createFlightMut.isPending || patchFlightMut.isPending}
                spots={sortedSpots}
                spotsLoading={spotsQuery.isLoading}
              />
              {createFlightMut.isError && (
                <Banner tone="warn">
                  {apiMessage(createFlightMut.error, 'Could not create the flight.')}
                </Banner>
              )}
              {patchFlightMut.isError && (
                <Banner tone="warn">
                  {apiMessage(patchFlightMut.error, 'Could not save the flight.')}
                </Banner>
              )}
              {deleteFlightMut.isError && (
                <Banner tone="warn">
                  {apiMessage(deleteFlightMut.error, 'Could not delete the flight.')}
                </Banner>
              )}
              <section aria-label="Spot flights list" className="space-y-2">
                <h2 className="text-sm font-semibold">Flights</h2>
                {flightsQuery.isLoading ? (
                  <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    Loading flights…
                  </p>
                ) : flightsQuery.isError ? (
                  <Banner tone="warn">
                    {apiMessage(flightsQuery.error, 'Could not load flights.')}
                  </Banner>
                ) : sortedFlights.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    No flights are defined yet. Use the form above to create one.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {sortedFlights.map((flight) => (
                      <FlightRow
                        key={flight.flight_id}
                        flight={flight}
                        onEdit={() => setFlightForm(formFromFlight(flight))}
                        onArmDelete={() =>
                          setFlightConfirmDelete((prev) => ({
                            ...prev,
                            [flight.flight_id]: true,
                          }))
                        }
                        onConfirmDelete={() => deleteFlightMut.mutate(flight.flight_id)}
                        confirming={flight.flight_id in flightConfirmDelete}
                        deleting={
                          deleteFlightMut.isPending &&
                          deleteFlightMut.variables === flight.flight_id
                        }
                      />
                    ))}
                  </ul>
                )}
              </section>
            </>
          ))}
      </section>

      <section
        id="panel-placements"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-placements"
        aria-label="Spot placements"
        hidden={tab !== 'placements'}
        className="space-y-3"
      >
        {tab === 'placements' &&
          (!canManage ? (
            manageDeniedBanner
          ) : (
            <>
              <PlacementFilters
                state={placementFilters}
                rangeOk={placementsRangeOk}
                rangeMessageId={rangeMessageId}
                onChange={setPlacementFilters}
              />
              {!placementsRangeOk && (
                <Banner tone="warn">
                  <span id={rangeMessageId}>
                    Pick a From date that is strictly before the Through date.
                  </span>
                </Banner>
              )}
              {placementsQuery.isLoading && (
                <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  Loading placements…
                </p>
              )}
              {placementsQuery.isError && (
                <Banner tone="warn">
                  {apiMessage(placementsQuery.error, 'Could not load placements.')}
                </Banner>
              )}
              {placementsQuery.data && <PlacementsTable rows={placementsQuery.data} />}
            </>
          ))}
      </section>

      <section
        id="panel-affidavits"
        role="tabpanel"
        tabIndex={0}
        aria-labelledby="tab-affidavits"
        aria-label="Underwriter affidavits"
        hidden={tab !== 'affidavits'}
        className="space-y-3"
      >
        {tab === 'affidavits' &&
          (!canReadAffidavits ? (
            affidavitsDeniedBanner
          ) : (
            <>
              <AffidavitFilters
                state={affidavitFilters}
                rangeOk={affidavitRangeOk}
                rangeMessageId={affidavitRangeMessageId}
                onChange={setAffidavitFilters}
              />
              {!affidavitRangeOk && (
                <Banner tone="warn">
                  <span id={affidavitRangeMessageId}>
                    Pick a From date that is on or before the Through date (the period is
                    inclusive both sides).
                  </span>
                </Banner>
              )}
              <AffidavitDownloadLinks state={affidavitFilters} disabled={!affidavitReady} />
              {!affidavitReady && (
                <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  Enter an underwriter name and a valid date range to load and download the
                  affidavit.
                </p>
              )}
              {affidavitQuery.isLoading && (
                <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  Loading affidavit…
                </p>
              )}
              {affidavitQuery.isError && (
                <Banner tone="warn">
                  {apiMessage(affidavitQuery.error, 'Could not load the affidavit.')}
                </Banner>
              )}
              {affidavitQuery.data && <AffidavitTable affidavit={affidavitQuery.data} />}
            </>
          ))}
      </section>
    </div>
  )
}
