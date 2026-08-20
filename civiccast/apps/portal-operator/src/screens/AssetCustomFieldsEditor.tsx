// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S22 asset-editor custom-field section. Renders one typed input per defined
// custom field and full-replaces this asset's values through the dedicated
// PUT /api/staff/assets/{id}/custom-fields endpoint — a SEPARATE round-trip
// from the core metadata PATCH, so the existing OCC/diff flow is untouched and
// the absence of any custom field stays the valid zero-state (the S22 key claim).
//
// Per-type widget (spec §5): text→input, longtext→textarea, number→number,
// date→date, boolean→checkbox, list→select(options), asset_ref→datalist over
// the asset library, producer_ref→datalist over producers. Required validation
// runs client-side (Save disabled + a role="alert" warning) and the server
// re-validates (list-is-an-option, refs resolve) — a 422 surfaces in the banner.
//
// S20: every control carries an aria-label (label text), uses useId() for
// label/control association, and required fields are marked.

import { useId, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  getAssetCustomFields,
  getProducerActivityReport,
  listCustomFieldDefs,
  listStaffAssets,
  putAssetCustomFields,
} from '../api/client'
import type { CustomFieldDef } from '../types/api.generated'
import {
  canonicalValueForType,
  inputKindForType,
  requiredFieldErrors,
  sortDefs,
} from './custom-fields-format'

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

const CONTROL_STYLE = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
} as const

/** One typed control for a single field def. Pure presentational. */
function CustomFieldInput({
  def,
  value,
  onChange,
  disabled,
  assetOptions,
  producerOptions,
}: {
  def: CustomFieldDef
  value: string
  onChange: (next: string) => void
  disabled: boolean
  assetOptions: Array<{ id: string; label: string }>
  producerOptions: Array<{ id: string; label: string }>
}) {
  const controlId = useId()
  const listId = useId()
  const kind = inputKindForType(def.type)
  const required = def.required ?? false
  const labelNode = (
    <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
      {def.label}
      {required ? <span style={{ color: 'var(--cc-err)' }}> *</span> : null}
    </span>
  )

  if (kind === 'textarea') {
    return (
      <label htmlFor={controlId} className="block">
        {labelNode}
        <textarea
          id={controlId}
          aria-label={def.label}
          rows={3}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md px-3 py-2 text-sm disabled:opacity-60"
          style={CONTROL_STYLE}
        />
      </label>
    )
  }

  if (kind === 'checkbox') {
    return (
      <label htmlFor={controlId} className="flex items-center gap-2 text-sm">
        <input
          id={controlId}
          aria-label={def.label}
          type="checkbox"
          checked={value === 'true'}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
        />
        <span>
          {def.label}
          {required ? <span style={{ color: 'var(--cc-err)' }}> *</span> : null}
        </span>
      </label>
    )
  }

  if (kind === 'select') {
    return (
      <label htmlFor={controlId} className="block">
        {labelNode}
        <select
          id={controlId}
          aria-label={def.label}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md px-3 py-2 text-sm disabled:opacity-60"
          style={CONTROL_STYLE}
        >
          <option value="">— Select —</option>
          {/* Ghost-guard: a stored value not in the current options stays visible
              and selectable-away rather than silently vanishing (UX-001 twin). */}
          {value && !(def.options ?? []).includes(value) && (
            <option value={value}>{value} (not in current options)</option>
          )}
          {(def.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </label>
    )
  }

  if (kind === 'asset_ref' || kind === 'producer_ref') {
    const options = kind === 'asset_ref' ? assetOptions : producerOptions
    return (
      <label htmlFor={controlId} className="block">
        {labelNode}
        <input
          id={controlId}
          aria-label={def.label}
          type="text"
          list={listId}
          value={value}
          disabled={disabled}
          placeholder={kind === 'asset_ref' ? 'Asset id' : 'Producer id'}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md px-3 py-2 text-sm disabled:opacity-60"
          style={CONTROL_STYLE}
        />
        <datalist id={listId}>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </datalist>
      </label>
    )
  }

  // text | number | date all share the <input> shape, differing by type attr.
  const inputType = kind === 'number' ? 'number' : kind === 'date' ? 'date' : 'text'
  return (
    <label htmlFor={controlId} className="block">
      {labelNode}
      <input
        id={controlId}
        aria-label={def.label}
        type={inputType}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md px-3 py-2 text-sm disabled:opacity-60"
        style={CONTROL_STYLE}
      />
    </label>
  )
}

/** The asset-editor's custom-fields section: typed inputs + a full-replace save. */
export function AssetCustomFieldsEditor({
  assetId,
  canWrite,
}: {
  assetId: string
  canWrite: boolean
}) {
  const qc = useQueryClient()

  const defsQuery = useQuery({ queryKey: ['custom-field-defs'], queryFn: listCustomFieldDefs })
  const valuesQuery = useQuery({
    queryKey: ['asset-custom-fields', assetId],
    queryFn: () => getAssetCustomFields(assetId),
  })
  // asset_ref / producer_ref pickers (best-effort; a failed list just yields an
  // empty datalist — the operator can still type an id).
  const assetsQuery = useQuery({ queryKey: ['staff-assets'], queryFn: listStaffAssets })
  const producersQuery = useQuery({
    queryKey: ['producer-activity'],
    queryFn: getProducerActivityReport,
    retry: false,
  })

  const defs = useMemo(() => sortDefs(defsQuery.data ?? []), [defsQuery.data])

  // Local edit buffer keyed by field_id, seeded once from the server values.
  // Keyed on the loaded values' identity so a refetch after save re-seeds.
  const serverValues = valuesQuery.data
  const [edit, setEdit] = useState<{ base: typeof serverValues; map: Record<string, string> } | null>(
    null,
  )
  const valuesByField = useMemo(() => {
    const map: Record<string, string> = {}
    for (const v of serverValues ?? []) map[v.field_id] = v.value
    return map
  }, [serverValues])
  const current = edit && edit.base === serverValues ? edit.map : valuesByField

  const setValue = (fieldId: string, next: string) => {
    const base = edit && edit.base === serverValues ? edit.map : valuesByField
    setEdit({ base: serverValues, map: { ...base, [fieldId]: next } })
  }

  const assetOptions = useMemo(
    () => (assetsQuery.data ?? []).map((a) => ({ id: a.asset_id, label: `${a.title} (${a.asset_id})` })),
    [assetsQuery.data],
  )
  const producerOptions = useMemo(
    () =>
      (producersQuery.data?.rows ?? []).map((r) => ({
        id: r.contributor_id,
        label: `${r.producer_name} (${r.contributor_id})`,
      })),
    [producersQuery.data],
  )

  const requiredErrors = requiredFieldErrors(defs, current)
  const hasRequiredError = requiredErrors.length > 0

  const mutation = useMutation({
    mutationFn: () => {
      // Full-replace: send every non-empty value as a canonical string. An empty
      // value is omitted (its absence is the zero-state); booleans are always
      // canonicalized so an explicit "false" persists.
      const values = defs
        .map((def) => {
          const raw = current[def.field_id] ?? ''
          const canonical = canonicalValueForType(def.type, def.type === 'boolean' ? raw === 'true' : raw)
          return { field_id: def.field_id, value: canonical }
        })
        .filter((entry) => entry.value.trim().length > 0)
      return putAssetCustomFields(assetId, { values })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['asset-custom-fields', assetId] })
      setEdit(null)
    },
  })

  return (
    <section
      aria-label="Custom fields"
      className="flex flex-col gap-4 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="m-0 text-sm font-semibold" style={{ color: 'var(--cc-ink)' }}>
        Custom fields
      </h2>

      {defsQuery.isLoading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading custom fields…
        </p>
      ) : defs.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No custom fields are defined. Define fields in Setup → Custom Fields to tag assets here.
        </p>
      ) : (
        <>
          {defs.map((def) => (
            <CustomFieldInput
              key={def.field_id}
              def={def}
              value={current[def.field_id] ?? ''}
              onChange={(next) => setValue(def.field_id, next)}
              disabled={!canWrite}
              assetOptions={assetOptions}
              producerOptions={producerOptions}
            />
          ))}

          {mutation.isError && (
            <div
              role="alert"
              className="rounded-md p-3 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              <strong>Save failed.</strong>{' '}
              <span style={{ color: 'var(--cc-ink-2)' }}>
                {apiMessage(mutation.error, 'A value failed validation.')}
              </span>
            </div>
          )}

          {canWrite && hasRequiredError && (
            <div
              role="alert"
              className="rounded-md p-3 text-xs"
              style={{
                background: 'var(--cc-warn-soft)',
                color: 'var(--cc-ink)',
                border: '1px solid var(--cc-line)',
              }}
            >
              <strong>Fill required fields before saving:</strong>{' '}
              <span style={{ color: 'var(--cc-ink-2)' }}>{requiredErrors.join(', ')}</span>
            </div>
          )}

          {canWrite && (
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                onClick={() => mutation.mutate()}
                disabled={hasRequiredError || mutation.isPending}
                className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
              >
                {mutation.isPending ? 'Saving…' : 'Save custom fields'}
              </button>
              {mutation.isSuccess && !edit && (
                <span className="text-[11px]" style={{ color: 'var(--cc-ok)' }}>
                  ✓ Saved.
                </span>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}
