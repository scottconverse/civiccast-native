// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator console: Setup > Custom Fields (S22). Define the station's
// user-defined metadata fields — key/label/type/options/required/searchable/
// api_exposed — and reorder them. Only a setup_admin may define fields (spec
// §4); other roles never reach this screen (it's a Setup surface).
//
// Key claims surfaced here:
//   - `key` is the immutable machine key (spec §6): editable on create, DISABLED
//     on edit. The label is always editable.
//   - Deleting a field with existing values is blocked by the server (409) unless
//     confirmed — never silent data loss. The screen surfaces a per-row confirm
//     after a 409, then re-issues with confirm=true (mirrors the EAS per-row
//     confirm discipline).
//   - searchable/api_exposed gate whether the field becomes a portal facet / is
//     exposed to the public API.

import { useId, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'

import {
  ApiError,
  createCustomFieldDef,
  deleteCustomFieldDef,
  getStaffIdentity,
  listCustomFieldDefs,
  updateCustomFieldDef,
} from '../api/client'
import type {
  CustomFieldDef,
  CustomFieldDefInput,
  CustomFieldDefUpdate,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import {
  CUSTOM_FIELD_TYPE_OPTIONS,
  type CustomFieldType,
  parseOptionsText,
  sortDefs,
  stringifyOptions,
} from './custom-fields-format'
import { EmptyState } from '../components/EmptyState'

// Spec §4: only setup_admin defines fields.
const ROLES = ['setup_admin']
// The single-station default — must match the backend router's _DEFAULT_STATION_ID
// so created defs land on the station the value/search endpoints read.
const DEFAULT_STATION_ID = 'civiccast-station'

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

interface FormState {
  // The field_id being edited, or null for "create new".
  editingFieldId: string | null
  key: string
  label: string
  type: CustomFieldType
  optionsText: string
  required: boolean
  searchable: boolean
  api_exposed: boolean
  order: number
}

const EMPTY_FORM: FormState = {
  editingFieldId: null,
  key: '',
  label: '',
  type: 'text',
  optionsText: '',
  required: false,
  searchable: true,
  api_exposed: true,
  order: 0,
}

function formFromDef(def: CustomFieldDef): FormState {
  return {
    editingFieldId: def.field_id,
    key: def.key,
    label: def.label,
    type: def.type,
    optionsText: stringifyOptions(def.options),
    required: def.required ?? false,
    searchable: def.searchable ?? true,
    api_exposed: def.api_exposed ?? true,
    order: def.order ?? 0,
  }
}

// Mint a stable field_id slug from the key (lowercase machine token) for new
// fields. The server stores it as the PK; deriving it from the key keeps it
// human-readable and unique per (station, key).
function fieldIdFromKey(key: string): string {
  const slug = key
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `cf-${slug || 'field'}`
}

/** The create/edit form for one field definition. */
function CustomFieldDefForm({
  form,
  onChange,
  onSubmit,
  onCancelEdit,
  pending,
}: {
  form: FormState
  onChange: (next: FormState) => void
  onSubmit: () => void
  onCancelEdit: () => void
  pending: boolean
}) {
  const keyId = useId()
  const labelId = useId()
  const typeId = useId()
  const optionsId = useId()
  const orderId = useId()
  const editing = form.editingFieldId != null
  const canSubmit = form.key.trim().length > 0 && form.label.trim().length > 0 && !pending

  return (
    <section
      aria-label={editing ? 'Edit custom field' : 'Define a custom field'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">{editing ? 'Edit field' : 'Define a new field'}</h2>

      <label htmlFor={keyId} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Field key (machine name)</span>
        <input
          id={keyId}
          aria-label="Field key"
          type="text"
          value={form.key}
          disabled={editing}
          placeholder="meeting_type"
          onChange={(e) => onChange({ ...form, key: e.target.value })}
          className="rounded-md px-2 py-1.5 disabled:opacity-60"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
        <span style={{ color: 'var(--cc-ink-3)' }}>
          {editing
            ? 'The key is fixed after creation so saved searches and reports keep working.'
            : 'Lowercase machine key (immutable once created). The label is what operators see.'}
        </span>
      </label>

      <label htmlFor={labelId} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Label (operator-facing)</span>
        <input
          id={labelId}
          aria-label="Field label"
          type="text"
          value={form.label}
          placeholder="Meeting type"
          onChange={(e) => onChange({ ...form, label: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
      </label>

      <label htmlFor={typeId} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Type</span>
        <select
          id={typeId}
          aria-label="Field type"
          value={form.type}
          onChange={(e) => onChange({ ...form, type: e.target.value as CustomFieldType })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        >
          {CUSTOM_FIELD_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      {form.type === 'list' && (
        <label htmlFor={optionsId} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>List options (one per line)</span>
          <textarea
            id={optionsId}
            aria-label="List options (one per line)"
            rows={4}
            value={form.optionsText}
            placeholder={'Regular\nSpecial\nWorkshop'}
            onChange={(e) => onChange({ ...form, optionsText: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={{
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          />
        </label>
      )}

      <div className="flex flex-wrap gap-4 text-xs">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="Required"
            checked={form.required}
            onChange={(e) => onChange({ ...form, required: e.target.checked })}
          />
          Required
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="Searchable"
            checked={form.searchable}
            onChange={(e) => onChange({ ...form, searchable: e.target.checked })}
          />
          Searchable (portal facet)
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            aria-label="Exposed to public API"
            checked={form.api_exposed}
            onChange={(e) => onChange({ ...form, api_exposed: e.target.checked })}
          />
          Exposed to public API
        </label>
      </div>

      <label htmlFor={orderId} className="grid gap-1 text-xs" style={{ maxWidth: '8rem' }}>
        <span style={{ color: 'var(--cc-ink-3)' }}>Order</span>
        <input
          id={orderId}
          aria-label="Order"
          type="number"
          value={form.order}
          onChange={(e) => onChange({ ...form, order: Number.parseInt(e.target.value, 10) || 0 })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
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
          {editing ? 'Save changes' : 'Create field'}
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

/** One row in the defined-fields list, with edit / reorder / delete controls. */
function DefRow({
  def,
  isFirst,
  isLast,
  onEdit,
  onMoveUp,
  onMoveDown,
  onDelete,
  onConfirmDelete,
  confirming,
  deleteError,
}: {
  def: CustomFieldDef
  isFirst: boolean
  isLast: boolean
  onEdit: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onDelete: () => void
  onConfirmDelete: () => void
  confirming: boolean
  deleteError: string | null
}) {
  const typeOpt = CUSTOM_FIELD_TYPE_OPTIONS.find((o) => o.value === def.type)
  return (
    <li
      className="space-y-1 rounded-md p-2 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <strong>{def.label}</strong>{' '}
          <span className="cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {def.key}
          </span>{' '}
          <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            · {typeOpt?.label ?? def.type}
            {def.required ? ' · required' : ''}
            {def.searchable ? ' · searchable' : ''}
            {def.api_exposed ? ' · public' : ''}
          </span>
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label={`Move ${def.label} up`}
            disabled={isFirst}
            onClick={onMoveUp}
            className="rounded-md px-2 py-1 text-xs disabled:opacity-40"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label={`Move ${def.label} down`}
            disabled={isLast}
            onClick={onMoveDown}
            className="rounded-md px-2 py-1 text-xs disabled:opacity-40"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            ↓
          </button>
          <button
            type="button"
            aria-label={`Edit ${def.label}`}
            onClick={onEdit}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Edit
          </button>
          {confirming ? (
            <button
              type="button"
              aria-label={`Confirm delete ${def.label}`}
              onClick={onConfirmDelete}
              className="rounded-md px-2 py-1 text-xs font-semibold"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              Confirm delete (cascades values)
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Delete ${def.label}`}
              onClick={onDelete}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {confirming && deleteError && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          {deleteError} Confirming will permanently delete this field and all its values.
        </p>
      )}
    </li>
  )
}

export function CustomFieldsScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, ROLES)

  const defsQuery = useQuery({
    queryKey: ['custom-field-defs'],
    queryFn: listCustomFieldDefs,
    enabled: canRead,
  })

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  // Per-row delete state: which field is awaiting a cascade confirm, and the 409
  // message to show. Keyed by field_id so confirming one never arms another.
  const [confirmDelete, setConfirmDelete] = useState<Record<string, string>>({})

  const invalidate = () => qc.invalidateQueries({ queryKey: ['custom-field-defs'] })

  const createMut = useMutation({
    mutationFn: (payload: CustomFieldDefInput) => createCustomFieldDef(payload),
    onSuccess: () => {
      invalidate()
      setForm(EMPTY_FORM)
    },
  })

  const updateMut = useMutation({
    mutationFn: (v: { fieldId: string; patch: CustomFieldDefUpdate }) =>
      updateCustomFieldDef(v.fieldId, v.patch),
    onSuccess: () => invalidate(),
  })

  const deleteMut = useMutation({
    mutationFn: (v: { fieldId: string; confirm: boolean }) =>
      deleteCustomFieldDef(v.fieldId, v.confirm),
    onSuccess: (_data, v) => {
      setConfirmDelete((prev) => {
        const next = { ...prev }
        delete next[v.fieldId]
        return next
      })
      invalidate()
    },
    onError: (err, v) => {
      // A 409 means values exist — surface the per-row cascade confirm rather
      // than silently dropping data (spec §6).
      if (err instanceof ApiError && err.status === 409) {
        setConfirmDelete((prev) => ({
          ...prev,
          [v.fieldId]: apiMessage(err, 'This field has values.'),
        }))
      }
    },
  })

  const handleSubmit = () => {
    if (form.editingFieldId != null) {
      // Edit: send only the editable attributes — key is immutable so it is
      // intentionally omitted from the patch.
      const patch: CustomFieldDefUpdate = {
        label: form.label.trim(),
        type: form.type,
        options: form.type === 'list' ? parseOptionsText(form.optionsText) : [],
        required: form.required,
        searchable: form.searchable,
        api_exposed: form.api_exposed,
        order: form.order,
      }
      updateMut.mutate(
        { fieldId: form.editingFieldId, patch },
        { onSuccess: () => setForm(EMPTY_FORM) },
      )
      return
    }
    const payload: CustomFieldDefInput = {
      field_id: fieldIdFromKey(form.key),
      station_id: DEFAULT_STATION_ID,
      key: form.key.trim(),
      label: form.label.trim(),
      type: form.type,
      options: form.type === 'list' ? parseOptionsText(form.optionsText) : [],
      required: form.required,
      searchable: form.searchable,
      api_exposed: form.api_exposed,
      order: form.order,
    }
    createMut.mutate(payload)
  }

  const moveBy = (defs: CustomFieldDef[], index: number, delta: number) => {
    const target = defs[index]
    const swapWith = defs[index + delta]
    if (!target || !swapWith) return
    // Swap the two rows' order values so the visible sort flips.
    updateMut.mutate({ fieldId: target.field_id, patch: { order: swapWith.order ?? 0 } })
    updateMut.mutate({ fieldId: swapWith.field_id, patch: { order: target.order ?? 0 } })
  }

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
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Custom Fields requires the setup admin role. Ask your station admin for access.
        </Banner>
      </div>
    )
  }

  const defs = sortDefs(defsQuery.data ?? [])

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Custom Fields</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Define your station&apos;s own metadata fields (meeting type, board members, episode
          number…). Typed and validated, set per asset, and — when searchable — shown as a portal
          search facet. The key is fixed after creation so saved searches and reports keep working.
        </p>
      </div>

      <CustomFieldDefForm
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        onCancelEdit={() => setForm(EMPTY_FORM)}
        pending={createMut.isPending || updateMut.isPending}
      />

      {createMut.isError && (
        <Banner tone="warn">{apiMessage(createMut.error, 'Could not create the field.')}</Banner>
      )}
      {updateMut.isError && (
        <Banner tone="warn">{apiMessage(updateMut.error, 'Could not save the field.')}</Banner>
      )}

      <section aria-label="Defined custom fields" className="space-y-2">
        <h2 className="text-sm font-semibold">Defined fields</h2>
        {defsQuery.isLoading ? (
          <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Loading fields…
          </p>
        ) : defsQuery.isError ? (
          <Banner tone="warn">{apiMessage(defsQuery.error, 'Could not load fields.')}</Banner>
        ) : defs.length === 0 ? (
          <EmptyState
            headline="No custom fields yet."
            body="Custom fields let this station tag its programs with its own labels — a department, a meeting body, a sponsor code. Add your first field with the form above and it appears here."
          />
        ) : (
          <ul className="space-y-1">
            {defs.map((def, index) => (
              <DefRow
                key={def.field_id}
                def={def}
                isFirst={index === 0}
                isLast={index === defs.length - 1}
                onEdit={() => setForm(formFromDef(def))}
                onMoveUp={() => moveBy(defs, index, -1)}
                onMoveDown={() => moveBy(defs, index, 1)}
                onDelete={() => deleteMut.mutate({ fieldId: def.field_id, confirm: false })}
                onConfirmDelete={() => deleteMut.mutate({ fieldId: def.field_id, confirm: true })}
                confirming={def.field_id in confirmDelete}
                deleteError={confirmDelete[def.field_id] ?? null}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
