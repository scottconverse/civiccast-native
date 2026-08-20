// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Plain-English labels + pure helpers for the S22 Custom Fields console (admin
// screen + asset-editor typed inputs). Split out of the screen modules so they
// stay react-refresh-clean (components-only export) and these helpers are
// unit-testable on their own — same split as ai-models-format.ts.
//
// Contracts encoded here (S22 §3/§5/§6):
//   - the 8 custom-field types map to a human label + an editor widget kind;
//   - `key` is immutable (the screen disables the input on edit; not enforced here);
//   - required validation runs client-side (server re-validates) — a required
//     field with an empty value is an error, but a required boolean is satisfied
//     by `false` (a choice WAS made, S20: never block on an explicit "no").

import type { CustomFieldDef } from '../types/api.generated'

export type Tone = 'neutral' | 'ok' | 'warn' | 'info'

export type CustomFieldType = CustomFieldDef['type']

// The editor widget a type renders as. `select` is the list dropdown; `asset_ref`
// / `producer_ref` render their own entity pickers (datalist-backed selects).
export type InputKind =
  | 'text'
  | 'textarea'
  | 'select'
  | 'date'
  | 'number'
  | 'checkbox'
  | 'asset_ref'
  | 'producer_ref'

const TYPE_LABELS: Record<CustomFieldType, string> = {
  text: 'Text',
  longtext: 'Long text',
  list: 'List (pick one)',
  date: 'Date',
  number: 'Number',
  boolean: 'Yes / no',
  asset_ref: 'Asset reference',
  producer_ref: 'Producer reference',
}

/** Human label for a custom-field type; never throws on an unexpected value. */
export function customFieldTypeLabel(type: CustomFieldType): string {
  return TYPE_LABELS[type] ?? type
}

// Fixed render order for the type <select> in the admin form (matches the spec
// §3 literal order and the backend CUSTOM_FIELD_TYPES tuple).
export const CUSTOM_FIELD_TYPE_OPTIONS: ReadonlyArray<{
  value: CustomFieldType
  label: string
}> = (
  ['text', 'longtext', 'list', 'date', 'number', 'boolean', 'asset_ref', 'producer_ref'] as const
).map((value) => ({ value, label: TYPE_LABELS[value] }))

/** The editor widget kind for a field type (drives which control the asset editor renders). */
export function inputKindForType(type: CustomFieldType): InputKind {
  switch (type) {
    case 'longtext':
      return 'textarea'
    case 'list':
      return 'select'
    case 'date':
      return 'date'
    case 'number':
      return 'number'
    case 'boolean':
      return 'checkbox'
    case 'asset_ref':
      return 'asset_ref'
    case 'producer_ref':
      return 'producer_ref'
    default:
      return 'text'
  }
}

/** Parse the admin form's list-options textarea (one option per line, blanks dropped). */
export function parseOptionsText(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

/** Render a def's options back to newline-joined text for the admin form. */
export function stringifyOptions(options: string[] | undefined): string {
  return (options ?? []).join('\n')
}

/** Canonicalize an editor value into the canonical string the API stores.
 *  A boolean control hands us a real boolean; everything else is already the
 *  canonical string (number/date inputs emit strings; the backend denormalizes
 *  value_num/value_date). */
export function canonicalValueForType(type: CustomFieldType, value: string | boolean): string {
  if (type === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

/** Whether a canonical value counts as "present" for a required-field check.
 *  Whitespace-only is empty; a boolean is always present once it has a value
 *  (both 'true' and 'false' are valid choices). */
function valuePresent(type: CustomFieldType, value: string | undefined): boolean {
  if (value == null) return false
  if (type === 'boolean') return value.length > 0
  return value.trim().length > 0
}

/** Labels of every required def missing a value in `valuesByFieldId` (client-side
 *  pre-check; the server re-validates list-is-an-option and ref-resolution). */
export function requiredFieldErrors(
  defs: CustomFieldDef[],
  valuesByFieldId: Record<string, string | undefined>,
): string[] {
  const missing: string[] = []
  for (const def of defs) {
    if (!def.required) continue
    if (!valuePresent(def.type, valuesByFieldId[def.field_id])) {
      missing.push(def.label)
    }
  }
  return missing
}

/** Order defs by `order` then `label` (the admin list + asset-editor render order).
 *  Returns a new array; the input is not mutated. */
export function sortDefs(defs: CustomFieldDef[]): CustomFieldDef[] {
  return [...defs].sort((a, b) => {
    const ao = a.order ?? 0
    const bo = b.order ?? 0
    if (ao !== bo) return ao - bo
    return a.label.localeCompare(b.label)
  })
}
