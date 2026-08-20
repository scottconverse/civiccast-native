// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S25 Operator console: Meeting agenda editor (slice 4).
//
// One screen with three stacked sections:
//
//   A. Agenda picker / metadata — dropdown of all agendas + a create form;
//      the selected agenda card shows status badge, source doc link, the
//      publish/unpublish button (publish refuses on zero items per DC-1 with a
//      surfaced 422), and a two-step delete confirm with the cascade warning.
//
//   B. Items list + editor — table of items (order, number, title, timecode,
//      doc anchor) with add/edit/delete and a two-step delete confirm. Drag
//      reordering is intentionally out of scope; the operator types the order
//      number. Instead of a disabled "Set from current video time" button, the
//      editor surfaces an honest helper link: open the meeting on the public
//      portal in another tab, find the moment, paste the seconds here. The
//      embedded player would require cross-app import of HlsPlayer (which
//      lives in the portal-public package, depends on hls.js, and is not
//      wired into the operator vite/tsconfig boundary). The link path keeps
//      the operator on a single source of truth (the public portal player)
//      without misleading affordances.
//
//   C. Bulk actions — "Sync from chapters" + a plain-text agenda import. The
//      PDF / DOCX path returns 415 from the server; we surface that as a
//      clear "plain text only today; PDF is a follow-up" banner.
//
// Role gate: records_clerk OR meeting_operator (matches the backend _AUTHOR
// set in civiccast/agenda/router.py).

import { useId, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'

import {
  ApiError,
  createAgendaItem,
  createMeetingAgenda,
  deleteAgendaItem,
  deleteMeetingAgenda,
  getStaffIdentity,
  importAgendaFromDoc,
  listAgendaItems,
  listMeetingAgendas,
  patchAgendaItem,
  patchMeetingAgenda,
  syncAgendaFromChapters,
} from '../api/client'
import type {
  AgendaItem,
  AgendaItemInput,
  AgendaItemUpdate,
  MeetingAgenda,
  MeetingAgendaInput,
  StaffIdentityResponse,
} from '../types/api.generated'
import { formatTimecode } from './agendas-format'
import { hasRole } from './contribution-format'

// Spec §4 / router _AUTHOR — records_clerk or meeting_operator may CRUD,
// publish, sync, and import.
const AUTHOR_ROLES = ['records_clerk', 'meeting_operator']
const DEFAULT_STATION_ID = 'civiccast-station'

/**
 * Build the public-portal "watch this meeting" URL for a given asset id, so
 * the UX-1 timecode tip can link the operator straight to the embedded
 * player. Returns null when the public portal base URL is not configured
 * (in which case the tip renders as prose without a hyperlink). The base
 * URL comes from VITE_PUBLIC_PORTAL_BASE_URL (e.g. "https://watch.example.gov"
 * or "/portal"); the trailing #/watch/{id} matches the portal-public router.
 */
function publicWatchUrlFor(assetId: string | null | undefined): string | null {
  if (!assetId) return null
  const base = (import.meta.env.VITE_PUBLIC_PORTAL_BASE_URL ?? '').trim()
  if (base.length === 0) return null
  const trimmed = base.replace(/\/+$/, '')
  return `${trimmed}/#/watch/${encodeURIComponent(assetId)}`
}

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
  // Match UnderwritingScreen's convention: warn = role="alert" (assertive),
  // everything else = role="status" (polite).
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

function StatusBadge({ status }: { status: 'draft' | 'published' }) {
  const ok = status === 'published'
  const c = ok ? TONE_COLORS.ok : TONE_COLORS.neutral
  return (
    <span
      aria-label={`Agenda status: ${status}`}
      className="cc-mono rounded-full px-2 py-0.5 text-xs"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {status}
    </span>
  )
}

// --- Create-agenda form -----------------------------------------------------

interface CreateAgendaFormState {
  agenda_id: string
  meeting_asset_id: string
  source_doc_url: string
}

const EMPTY_CREATE_FORM: CreateAgendaFormState = {
  agenda_id: '',
  meeting_asset_id: '',
  source_doc_url: '',
}

function CreateAgendaForm({
  form,
  onChange,
  onSubmit,
  pending,
}: {
  form: CreateAgendaFormState
  onChange: (next: CreateAgendaFormState) => void
  onSubmit: () => void
  pending: boolean
}) {
  const idAg = useId()
  const idMa = useId()
  const idUrl = useId()
  const canSubmit =
    form.agenda_id.trim().length > 0 && form.meeting_asset_id.trim().length > 0 && !pending
  return (
    <section
      aria-label="Create a new meeting agenda"
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">Create new agenda</h2>
      <label htmlFor={idAg} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Agenda ID (slug)</span>
        <input
          id={idAg}
          aria-label="Agenda ID"
          type="text"
          value={form.agenda_id}
          placeholder="council-2026-01"
          onChange={(e) => onChange({ ...form, agenda_id: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idMa} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Meeting asset ID</span>
        <input
          id={idMa}
          aria-label="Meeting asset ID"
          type="text"
          value={form.meeting_asset_id}
          placeholder="asset-council-2026-01"
          onChange={(e) => onChange({ ...form, meeting_asset_id: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>
      <label htmlFor={idUrl} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Source doc URL (optional)</span>
        <input
          id={idUrl}
          aria-label="Source doc URL"
          type="url"
          pattern="https?://.*"
          value={form.source_doc_url}
          placeholder="https://example.gov/agendas/council-2026-01.pdf"
          onChange={(e) => onChange({ ...form, source_doc_url: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
        <span style={{ color: 'var(--cc-ink-3)' }}>
          Link to the published PDF/HTML agenda the resident can read alongside the video.
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          Create agenda
        </button>
      </div>
    </section>
  )
}

// --- Selected-agenda card ---------------------------------------------------

function SelectedAgendaCard({
  agenda,
  itemCount,
  onPublish,
  onUnpublish,
  onArmDelete,
  onConfirmDelete,
  confirming,
  publishing,
  deleting,
  publishError,
  deleteError,
}: {
  agenda: MeetingAgenda
  itemCount: number
  onPublish: () => void
  onUnpublish: () => void
  onArmDelete: () => void
  onConfirmDelete: () => void
  confirming: boolean
  publishing: boolean
  deleting: boolean
  publishError: string | null
  deleteError: string | null
}) {
  const status = agenda.status ?? 'draft'
  const canPublish = status === 'draft' && itemCount > 0
  return (
    <section
      aria-label="Selected agenda"
      className="space-y-2 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <strong className="cc-mono text-sm">{agenda.agenda_id}</strong>
            <StatusBadge status={status} />
          </div>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            meeting asset:{' '}
            <span className="cc-mono">{agenda.meeting_asset_id}</span>
          </div>
          {agenda.source_doc_url ? (
            <div className="text-xs">
              <a
                href={agenda.source_doc_url}
                target="_blank"
                rel="noreferrer noopener"
                aria-label="Open source agenda document"
                style={{ color: 'var(--cc-brand-2)' }}
              >
                Source doc ↗
              </a>
            </div>
          ) : (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              No source doc URL.
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {status === 'draft' ? (
            <button
              type="button"
              aria-label="Publish this agenda"
              disabled={!canPublish || publishing}
              onClick={onPublish}
              title={
                itemCount === 0
                  ? 'Publish needs at least one item — add one below or sync from chapters.'
                  : undefined
              }
              className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              {publishing ? 'Publishing…' : 'Publish'}
            </button>
          ) : (
            <button
              type="button"
              aria-label="Unpublish this agenda"
              disabled={publishing}
              onClick={onUnpublish}
              className="rounded-md px-3 py-1.5 text-xs font-medium disabled:opacity-50"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              {publishing ? 'Saving…' : 'Unpublish'}
            </button>
          )}
          {confirming ? (
            <button
              type="button"
              aria-label="Confirm delete agenda"
              disabled={deleting}
              onClick={onConfirmDelete}
              className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              {deleting ? 'Deleting…' : 'Confirm delete'}
            </button>
          ) : (
            <button
              type="button"
              aria-label="Delete this agenda"
              onClick={onArmDelete}
              className="rounded-md px-3 py-1.5 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {status === 'draft' && itemCount === 0 && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Publish needs at least one item. Add one below or sync from the meeting asset&apos;s
          chapters.
        </p>
      )}
      {publishError && <Banner tone="warn">{publishError}</Banner>}
      {confirming && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Confirming will also delete every item under this agenda.
        </p>
      )}
      {deleteError && <Banner tone="warn">{deleteError}</Banner>}
    </section>
  )
}

// --- Item form --------------------------------------------------------------

interface ItemFormState {
  /** null when adding; item_id otherwise. */
  editingItemId: string | null
  item_id: string
  order: string
  number: string
  title: string
  video_timecode_s: string
  doc_anchor: string
  notes: string
}

const EMPTY_ITEM_FORM: ItemFormState = {
  editingItemId: null,
  item_id: '',
  order: '0',
  number: '',
  title: '',
  video_timecode_s: '',
  doc_anchor: '',
  notes: '',
}

function formFromItem(item: AgendaItem): ItemFormState {
  return {
    editingItemId: item.item_id,
    item_id: item.item_id,
    order: String(item.order),
    number: item.number ?? '',
    title: item.title,
    video_timecode_s: item.video_timecode_s == null ? '' : String(item.video_timecode_s),
    doc_anchor: item.doc_anchor ?? '',
    notes: item.notes ?? '',
  }
}

function parseOptionalInt(text: string): { ok: boolean; value: number | null } {
  const trimmed = text.trim()
  if (trimmed.length === 0) return { ok: true, value: null }
  if (!/^\d+$/.test(trimmed)) return { ok: false, value: null }
  const n = Number.parseInt(trimmed, 10)
  if (!Number.isFinite(n) || n < 0) return { ok: false, value: null }
  return { ok: true, value: n }
}

function ItemForm({
  form,
  onChange,
  onSubmit,
  onCancelEdit,
  pending,
  publicPortalUrl,
}: {
  form: ItemFormState
  onChange: (next: ItemFormState) => void
  onSubmit: () => void
  onCancelEdit: () => void
  pending: boolean
  /**
   * Honest UX-1 fix: link the operator to the public portal page for the
   * selected meeting asset so they can find the timecode in the live player
   * and paste it here. Null when the agenda has no meeting asset bound (the
   * link section then renders nothing). Embedding the player on this screen
   * is a follow-up: HlsPlayer lives in the portal-public package and
   * importing it across apps would require restructuring vite/tsconfig path
   * aliases that are deliberately scoped to ./src per app.
   */
  publicPortalUrl: string | null
}) {
  const idItem = useId()
  const idOrder = useId()
  const idNum = useId()
  const idTitle = useId()
  const idTc = useId()
  const idAnchor = useId()
  const idNotes = useId()
  const editing = form.editingItemId != null
  const orderParsed = parseOptionalInt(form.order)
  const tcParsed = parseOptionalInt(form.video_timecode_s)
  const canSubmit =
    (editing || form.item_id.trim().length > 0) &&
    form.title.trim().length > 0 &&
    orderParsed.ok &&
    orderParsed.value != null &&
    tcParsed.ok &&
    !pending

  return (
    <section
      aria-label={editing ? 'Edit agenda item' : 'Add agenda item'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h3 className="text-sm font-semibold">{editing ? 'Edit item' : 'Add item'}</h3>

      {!editing && (
        <label htmlFor={idItem} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Item ID (slug)</span>
          <input
            id={idItem}
            aria-label="Item ID"
            type="text"
            value={form.item_id}
            placeholder="item-01-call-to-order"
            onChange={(e) => onChange({ ...form, item_id: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={idOrder} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Order</span>
          <input
            id={idOrder}
            aria-label="Order"
            type="number"
            min={0}
            value={form.order}
            onChange={(e) => onChange({ ...form, order: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          {!orderParsed.ok && (
            <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
              Order must be a whole non-negative number.
            </span>
          )}
        </label>
        <label htmlFor={idNum} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Number (label, optional)</span>
          <input
            id={idNum}
            aria-label="Number"
            type="text"
            value={form.number}
            placeholder="1.a"
            onChange={(e) => onChange({ ...form, number: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
      </div>

      <label htmlFor={idTitle} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Title</span>
        <input
          id={idTitle}
          aria-label="Title"
          type="text"
          value={form.title}
          placeholder="Call to order"
          onChange={(e) => onChange({ ...form, title: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label htmlFor={idTc} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Video timecode (seconds, optional)</span>
          <input
            id={idTc}
            aria-label="Video timecode (seconds)"
            aria-describedby={`${idTc}-tip`}
            type="number"
            min={0}
            value={form.video_timecode_s}
            placeholder="e.g. 125"
            onChange={(e) => onChange({ ...form, video_timecode_s: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          <span
            id={`${idTc}-tip`}
            className="text-xs"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            Tip:{' '}
            {publicPortalUrl ? (
              <>
                <a
                  href={publicPortalUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label="Open this meeting on the public portal in a new tab to find the timecode"
                  style={{ color: 'var(--cc-brand-2)' }}
                >
                  open the meeting on the public portal ↗
                </a>{' '}
                in another tab, find the moment in the player, then paste the seconds here.
              </>
            ) : (
              <>
                open the meeting on the public portal in another tab, find the moment in
                the player, then paste the seconds here.
              </>
            )}
          </span>
          {!tcParsed.ok && (
            <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
              Timecode must be a whole non-negative number of seconds (or blank).
            </span>
          )}
        </label>
        <label htmlFor={idAnchor} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Doc anchor (optional)</span>
          <input
            id={idAnchor}
            aria-label="Doc anchor"
            type="text"
            value={form.doc_anchor}
            placeholder="#item-1a"
            onChange={(e) => onChange({ ...form, doc_anchor: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
      </div>

      <label htmlFor={idNotes} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Notes (optional)</span>
        <textarea
          id={idNotes}
          aria-label="Notes"
          rows={3}
          value={form.notes}
          placeholder="Operator-private notes; not shown to viewers."
          onChange={(e) => onChange({ ...form, notes: e.target.value })}
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
          {editing ? 'Save item' : 'Add item'}
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

// --- Items table ------------------------------------------------------------

function ItemsTable({
  items,
  onEdit,
  onArmDelete,
  onConfirmDelete,
  confirming,
  deleting,
}: {
  items: AgendaItem[]
  onEdit: (item: AgendaItem) => void
  onArmDelete: (itemId: string) => void
  onConfirmDelete: (itemId: string) => void
  confirming: Record<string, true>
  deleting: string | null
}) {
  if (items.length === 0) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        No items on this agenda yet. Add one with the form above, or run &ldquo;Sync from
        chapters&rdquo; in the Bulk actions section if the meeting asset already has chapter
        markers.
      </p>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="w-full text-sm" aria-label="Agenda items">
        <thead>
          <tr style={{ color: 'var(--cc-ink-3)' }}>
            <th className="px-2 py-1 text-left">Order</th>
            <th className="px-2 py-1 text-left">Number</th>
            <th className="px-2 py-1 text-left">Title</th>
            <th className="px-2 py-1 text-left">Timecode</th>
            <th className="px-2 py-1 text-left">Doc anchor</th>
            <th className="px-2 py-1 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isConfirming = item.item_id in confirming
            const isDeleting = deleting === item.item_id
            return (
              <tr key={item.item_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
                <td className="cc-mono cc-tabular px-2 py-1 text-xs">{item.order}</td>
                <td className="cc-mono px-2 py-1 text-xs">{item.number ?? '—'}</td>
                <td className="px-2 py-1 text-xs">{item.title}</td>
                <td className="cc-mono cc-tabular px-2 py-1 text-xs">
                  {formatTimecode(item.video_timecode_s ?? null)}
                </td>
                <td className="cc-mono px-2 py-1 text-xs">{item.doc_anchor ?? '—'}</td>
                <td className="px-2 py-1 text-right">
                  <div className="inline-flex flex-wrap items-center gap-1">
                    <button
                      type="button"
                      aria-label={`Edit ${item.title}`}
                      onClick={() => onEdit(item)}
                      className="rounded-md px-2 py-1 text-xs font-medium"
                      style={{
                        background: 'var(--cc-surface)',
                        border: '1px solid var(--cc-line)',
                      }}
                    >
                      Edit
                    </button>
                    {isConfirming ? (
                      <button
                        type="button"
                        aria-label={`Confirm delete ${item.title}`}
                        disabled={isDeleting}
                        onClick={() => onConfirmDelete(item.item_id)}
                        className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
                        style={{
                          background: 'var(--cc-err-soft)',
                          border: '1px solid var(--cc-err)',
                        }}
                      >
                        {isDeleting ? 'Deleting…' : 'Confirm delete'}
                      </button>
                    ) : (
                      <button
                        type="button"
                        aria-label={`Delete ${item.title}`}
                        onClick={() => onArmDelete(item.item_id)}
                        className="rounded-md px-2 py-1 text-xs font-medium"
                        style={{
                          background: 'var(--cc-surface)',
                          border: '1px solid var(--cc-line)',
                        }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// --- Screen -----------------------------------------------------------------

export function AgendasScreen() {
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
        <AuthRequiredState error={identityQuery.error} />
      </div>
    )
  }
  const canAuthor = hasRole(identityQuery.data, AUTHOR_ROLES)
  if (!canAuthor) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Agendas require the records clerk or meeting operator role. Ask your station admin
          for access.
        </Banner>
      </div>
    )
  }
  return <AgendasBody />
}

function AgendasBody() {
  const qc = useQueryClient()

  const agendasQuery = useQuery({
    queryKey: ['meeting-agendas'],
    queryFn: () => listMeetingAgendas(),
  })

  const agendas = useMemo(() => {
    const list = agendasQuery.data ?? []
    return [...list].sort((a, b) => {
      const ma = a.meeting_asset_id.localeCompare(b.meeting_asset_id)
      if (ma !== 0) return ma
      return a.agenda_id.localeCompare(b.agenda_id)
    })
  }, [agendasQuery.data])

  // Operator-picked agenda id; `null` means "fall through to the first agenda
  // in the list". We derive the EFFECTIVE selection during render so we never
  // call setState from an effect just to seed a default (react-hooks/set-state-
  // in-effect). A freshly-created agenda gets `setPickedAgendaId(created.id)`
  // from the create-mutation onSuccess so the user is taken straight to it.
  const [pickedAgendaId, setPickedAgendaId] = useState<string | null>(null)

  const selectedAgendaId = useMemo<string | null>(() => {
    if (pickedAgendaId != null && agendas.some((a) => a.agenda_id === pickedAgendaId)) {
      return pickedAgendaId
    }
    return agendas.length > 0 ? agendas[0].agenda_id : null
  }, [agendas, pickedAgendaId])

  const selectedAgenda = useMemo(
    () => agendas.find((a) => a.agenda_id === selectedAgendaId) ?? null,
    [agendas, selectedAgendaId],
  )

  // --- Create agenda (lives on the body so a successful create can clear the
  // form without remounting the picker). ---
  const [createForm, setCreateForm] = useState<CreateAgendaFormState>(EMPTY_CREATE_FORM)
  const invalidateAgendas = () => qc.invalidateQueries({ queryKey: ['meeting-agendas'] })

  const createAgendaMut = useMutation({
    mutationFn: (payload: MeetingAgendaInput) => createMeetingAgenda(payload),
    onSuccess: (created) => {
      invalidateAgendas()
      setCreateForm(EMPTY_CREATE_FORM)
      setPickedAgendaId(created.agenda_id)
    },
  })

  const handleSubmitCreate = () => {
    const payload: MeetingAgendaInput = {
      agenda_id: createForm.agenda_id.trim(),
      station_id: DEFAULT_STATION_ID,
      meeting_asset_id: createForm.meeting_asset_id.trim(),
      source_doc_url:
        createForm.source_doc_url.trim() === '' ? null : createForm.source_doc_url.trim(),
    }
    createAgendaMut.mutate(payload)
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Agendas</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Build and publish a meeting agenda the resident sees alongside the recording. Agendas
          stay drafts until published; published agendas appear on the public meeting page.
          Publishing needs at least one item.
        </p>
      </div>

      {/* UX-3 fix: hide the picker entirely on the empty-state path so the
         "No agendas yet" banner below is the only empty-state surface (the
         disabled placeholder option duplicated the banner copy and confused
         screen readers walking the tab order). The picker reappears as soon
         as at least one agenda exists. */}
      {(agendasQuery.isLoading || agendas.length > 0) && (
        <section
          aria-label="Agenda picker"
          className="space-y-3 rounded-md p-4 text-sm"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          <AgendaPicker
            agendas={agendas}
            loading={agendasQuery.isLoading}
            value={selectedAgendaId}
            onChange={setPickedAgendaId}
          />
        </section>
      )}

      <CreateAgendaForm
        form={createForm}
        onChange={setCreateForm}
        onSubmit={handleSubmitCreate}
        pending={createAgendaMut.isPending}
      />
      {createAgendaMut.isError && (
        <Banner tone="warn">
          {apiMessage(createAgendaMut.error, 'Could not create the agenda.')}
        </Banner>
      )}

      {selectedAgenda ? (
        // Keyed by agenda_id so all per-agenda transient state (item form,
        // delete-confirm flags, import textarea, mutation results) resets
        // automatically when the operator picks a different agenda. This is
        // the structural alternative to a reset-via-effect (which would
        // trigger react-hooks/set-state-in-effect).
        <SelectedAgendaSection
          key={selectedAgenda.agenda_id}
          agenda={selectedAgenda}
          onAgendaDeleted={() => setPickedAgendaId(null)}
        />
      ) : (
        !agendasQuery.isLoading && (
          <Banner tone="info">
            No agendas yet. Use the form above to create one — it starts as a draft and only goes
            public once you publish it.
          </Banner>
        )
      )}
    </div>
  )
}

/**
 * Per-agenda card + items + bulk actions. Mounted with `key={agenda_id}` so
 * switching agendas remounts the component and clears the local state (item
 * form, per-row delete confirms, import textarea, mutation results) — the
 * structural alternative to a reset-via-effect that would trip
 * react-hooks/set-state-in-effect.
 */
function SelectedAgendaSection({
  agenda,
  onAgendaDeleted,
}: {
  agenda: MeetingAgenda
  onAgendaDeleted: () => void
}) {
  const qc = useQueryClient()
  const agendaId = agenda.agenda_id

  const invalidateAgendas = () => qc.invalidateQueries({ queryKey: ['meeting-agendas'] })
  const invalidateItems = () => qc.invalidateQueries({ queryKey: ['agenda-items', agendaId] })

  const itemsQuery = useQuery({
    queryKey: ['agenda-items', agendaId],
    queryFn: () => listAgendaItems(agendaId),
  })
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data])

  // Agenda-level UI state
  const [confirmDeleteAgenda, setConfirmDeleteAgenda] = useState(false)

  const publishMut = useMutation({
    mutationFn: (statusValue: 'draft' | 'published') =>
      patchMeetingAgenda(agendaId, { status: statusValue }),
    onSuccess: () => invalidateAgendas(),
  })

  const deleteAgendaMut = useMutation({
    mutationFn: () => deleteMeetingAgenda(agendaId),
    onSuccess: () => {
      setConfirmDeleteAgenda(false)
      invalidateAgendas()
      onAgendaDeleted()
    },
  })

  // Item-level UI state
  const [itemForm, setItemForm] = useState<ItemFormState>(EMPTY_ITEM_FORM)
  const [confirmDeleteItem, setConfirmDeleteItem] = useState<Record<string, true>>({})

  const createItemMut = useMutation({
    mutationFn: (payload: AgendaItemInput) => createAgendaItem(agendaId, payload),
    onSuccess: () => {
      invalidateItems()
      setItemForm(EMPTY_ITEM_FORM)
    },
  })

  const patchItemMut = useMutation({
    mutationFn: (v: { itemId: string; patch: AgendaItemUpdate }) =>
      patchAgendaItem(agendaId, v.itemId, v.patch),
    onSuccess: () => {
      invalidateItems()
      setItemForm(EMPTY_ITEM_FORM)
    },
  })

  const deleteItemMut = useMutation({
    mutationFn: (itemId: string) => deleteAgendaItem(agendaId, itemId),
    onSuccess: (_data, itemId) => {
      setConfirmDeleteItem((prev) => {
        const next = { ...prev }
        delete next[itemId]
        return next
      })
      invalidateItems()
    },
  })

  // Bulk-action UI state
  const syncMut = useMutation({
    mutationFn: () => syncAgendaFromChapters(agendaId),
    onSuccess: () => invalidateItems(),
  })

  const [importText, setImportText] = useState('')
  const importMut = useMutation({
    mutationFn: (text: string) => importAgendaFromDoc(agendaId, text),
    onSuccess: () => {
      invalidateItems()
      setImportText('')
    },
  })

  const handleSubmitItem = () => {
    const order = parseOptionalInt(itemForm.order)
    if (!order.ok || order.value == null) return
    const tc = parseOptionalInt(itemForm.video_timecode_s)
    if (!tc.ok) return
    if (itemForm.editingItemId != null) {
      const patch: AgendaItemUpdate = {
        order: order.value,
        number: itemForm.number.trim() === '' ? null : itemForm.number.trim(),
        title: itemForm.title.trim(),
        video_timecode_s: tc.value,
        doc_anchor: itemForm.doc_anchor.trim() === '' ? null : itemForm.doc_anchor.trim(),
        notes: itemForm.notes.trim() === '' ? null : itemForm.notes,
      }
      patchItemMut.mutate({ itemId: itemForm.editingItemId, patch })
      return
    }
    const payload: AgendaItemInput = {
      item_id: itemForm.item_id.trim(),
      agenda_id: agendaId,
      order: order.value,
      number: itemForm.number.trim() === '' ? null : itemForm.number.trim(),
      title: itemForm.title.trim(),
      video_timecode_s: tc.value,
      doc_anchor: itemForm.doc_anchor.trim() === '' ? null : itemForm.doc_anchor.trim(),
      notes: itemForm.notes.trim() === '' ? null : itemForm.notes,
    }
    createItemMut.mutate(payload)
  }

  const publishError =
    publishMut.isError && publishMut.variables === 'published'
      ? apiMessage(publishMut.error, 'Could not publish the agenda.')
      : null
  const unpublishError =
    publishMut.isError && publishMut.variables === 'draft'
      ? apiMessage(publishMut.error, 'Could not unpublish the agenda.')
      : null
  const deleteAgendaError = deleteAgendaMut.isError
    ? apiMessage(deleteAgendaMut.error, 'Could not delete the agenda.')
    : null

  const importIs415 =
    importMut.isError && importMut.error instanceof ApiError && importMut.error.status === 415

  return (
    <>
      <SelectedAgendaCard
        agenda={agenda}
        itemCount={items.length}
        onPublish={() => publishMut.mutate('published')}
        onUnpublish={() => publishMut.mutate('draft')}
        onArmDelete={() => setConfirmDeleteAgenda(true)}
        onConfirmDelete={() => deleteAgendaMut.mutate()}
        confirming={confirmDeleteAgenda}
        publishing={publishMut.isPending}
        deleting={deleteAgendaMut.isPending}
        publishError={publishError ?? unpublishError}
        deleteError={deleteAgendaError}
      />

      <section
        aria-label="Agenda items"
        className="space-y-3 rounded-md p-4 text-sm"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="text-sm font-semibold">Items</h2>
        <ItemForm
          form={itemForm}
          onChange={setItemForm}
          onSubmit={handleSubmitItem}
          onCancelEdit={() => setItemForm(EMPTY_ITEM_FORM)}
          pending={createItemMut.isPending || patchItemMut.isPending}
          publicPortalUrl={publicWatchUrlFor(agenda.meeting_asset_id)}
        />
        {createItemMut.isError && (
          <Banner tone="warn">
            {apiMessage(createItemMut.error, 'Could not create the item.')}
          </Banner>
        )}
        {patchItemMut.isError && (
          <Banner tone="warn">
            {apiMessage(patchItemMut.error, 'Could not save the item.')}
          </Banner>
        )}
        {deleteItemMut.isError && (
          <Banner tone="warn">
            {apiMessage(deleteItemMut.error, 'Could not delete the item.')}
          </Banner>
        )}
        {itemsQuery.isLoading ? (
          <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Loading items…
          </p>
        ) : itemsQuery.isError && items.length === 0 ? (
          <Banner tone="warn">{apiMessage(itemsQuery.error, 'Could not load items.')}</Banner>
        ) : (
          <>
            {/* UX-4 fix: when a background refetch fails but a prior cache is
               still on screen, react-query keeps the old rows AND flips
               isError true. Without this pill the operator thinks the table
               is fresh. The Banner above only renders when no cache exists. */}
            {itemsQuery.isError && items.length > 0 && (
              <p
                role="status"
                aria-live="polite"
                className="rounded-md px-2 py-1 text-xs"
                style={{
                  background: 'var(--cc-warn-soft)',
                  border: '1px solid var(--cc-warn)',
                  color: 'var(--cc-ink-2)',
                }}
              >
                Items list may be stale — last refresh failed
                {itemsQuery.error
                  ? ` (${apiMessage(itemsQuery.error, 'reason unknown')}).`
                  : '.'}{' '}
                The rows below are from the previous successful load.
              </p>
            )}
            <ItemsTable
              items={items}
              onEdit={(item) => setItemForm(formFromItem(item))}
              onArmDelete={(itemId) =>
                setConfirmDeleteItem((prev) => ({ ...prev, [itemId]: true }))
              }
              onConfirmDelete={(itemId) => deleteItemMut.mutate(itemId)}
              confirming={confirmDeleteItem}
              deleting={
                deleteItemMut.isPending && deleteItemMut.variables
                  ? deleteItemMut.variables
                  : null
              }
            />
          </>
        )}
      </section>

      <section
        aria-label="Bulk actions"
        className="space-y-3 rounded-md p-4 text-sm"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="text-sm font-semibold">Bulk actions</h2>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              aria-label="Sync agenda items from chapter markers"
              disabled={syncMut.isPending}
              onClick={() => syncMut.mutate()}
              className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              {syncMut.isPending ? 'Syncing…' : 'Sync from chapters'}
            </button>
            <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Seeds draft items from the meeting asset&apos;s chapter markers. Safe to re-run:
              operator edits at the same order are preserved.
            </span>
          </div>
          {syncMut.isSuccess && (
            <Banner tone="ok">
              Synced {syncMut.data?.length ?? 0} new item
              {(syncMut.data?.length ?? 0) === 1 ? '' : 's'} from chapter markers.
            </Banner>
          )}
          {syncMut.isError && (
            <Banner tone="warn">
              {apiMessage(syncMut.error, 'Could not sync from chapters.')}
            </Banner>
          )}
        </div>

        <div className="space-y-2">
          <label className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>
              Import from doc (paste plain-text agenda, one item per line)
            </span>
            <textarea
              aria-label="Plain-text agenda to import"
              rows={5}
              value={importText}
              placeholder={
                '1. Call to order\n2. Approval of minutes\n3. Public comment\n4. New business'
              }
              onChange={(e) => setImportText(e.target.value)}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              aria-label="Import agenda items from pasted text"
              disabled={importMut.isPending || importText.trim().length === 0}
              onClick={() => importMut.mutate(importText)}
              className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              {importMut.isPending ? 'Importing…' : 'Import'}
            </button>
            <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Plain text only today; PDF / DOCX support is a follow-up (the server returns 415
              today, which we surface here).
            </span>
          </div>
          {importMut.isSuccess && (
            <Banner tone="ok">
              Imported {importMut.data?.length ?? 0} item
              {(importMut.data?.length ?? 0) === 1 ? '' : 's'} from the pasted text.
            </Banner>
          )}
          {importMut.isError && (
            <Banner tone="warn">
              {importIs415
                ? 'Only plain-text agendas import here today. PDF support is a follow-up.'
                : apiMessage(importMut.error, 'Could not import the agenda.')}
            </Banner>
          )}
        </div>
      </section>
    </>
  )
}

function AgendaPicker({
  agendas,
  loading,
  value,
  onChange,
}: {
  agendas: MeetingAgenda[]
  loading: boolean
  value: string | null
  onChange: (id: string) => void
}) {
  const idSel = useId()
  return (
    <label htmlFor={idSel} className="grid gap-1 text-xs">
      <span style={{ color: 'var(--cc-ink-3)' }}>Pick an agenda</span>
      <select
        id={idSel}
        aria-label="Pick an agenda"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md px-2 py-1.5"
        style={INPUT_STYLE}
      >
        {/* The picker is hidden by the parent when `agendas.length === 0`
           (UX-3), so the only placeholder cases that actually render are
           "loading" and "pick one of N". */}
        <option value="" disabled>
          {loading ? 'Loading agendas…' : 'Pick…'}
        </option>
        {agendas.map((a) => (
          <option key={a.agenda_id} value={a.agenda_id}>
            {a.meeting_asset_id} — {a.agenda_id} ({a.status ?? 'draft'})
          </option>
        ))}
      </select>
    </label>
  )
}
