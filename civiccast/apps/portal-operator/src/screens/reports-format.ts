// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Pure formatting helpers for the S23 Reports + EPG screens. Kept separate
// from the React surfaces so they can be unit-tested without rendering.

/**
 * Format a duration in seconds as "Hh Mm Ss" (e.g. 3725 -> "1h 2m 5s"). Used
 * for "total airtime" columns on Shows + Hours-by-Category reports. Negative
 * values are clamped to zero; non-finite values yield "0s" so a bad upstream
 * value never crashes the row render.
 */
export function formatHms(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return '0s'
  const secs = Math.floor(totalSeconds)
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = secs % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h}h`)
  if (h > 0 || m > 0) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}

/**
 * Format a count of hours (fractional, as returned by hours-by-category) as
 * a two-decimal string with the "h" unit (e.g. 12.3456 -> "12.35h").
 */
export function formatHours(hours: number): string {
  if (!Number.isFinite(hours) || hours <= 0) return '0.00h'
  return `${hours.toFixed(2)}h`
}

/**
 * Parse a textarea of `key=value` pairs (one per line) into a Record. Blank
 * lines and `#` comment lines are ignored. Whitespace around `=` is trimmed.
 * A line without `=` is dropped (the form surfaces a one-line hint about
 * shape; we do not throw — the user sees what was parsed in the live preview).
 */
export function parseFieldMapText(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  if (!text) return out
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (line.length === 0) continue
    if (line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    const key = line.slice(0, eq).trim()
    const value = line.slice(eq + 1).trim()
    if (key.length === 0) continue
    out[key] = value
  }
  return out
}

/**
 * Reverse of parseFieldMapText — render a Record back into a textarea body
 * so the patch form can pre-populate from server state.
 */
export function stringifyFieldMap(map: Record<string, string> | undefined | null): string {
  if (!map) return ''
  const keys = Object.keys(map).sort()
  return keys.map((k) => `${k}=${map[k] ?? ''}`).join('\n')
}

/**
 * The copy for the field_not_found banner on the Hours-by-Category report.
 * Lifted out of JSX so the test can assert exact text without snapshotting.
 */
export function fieldNotFoundBanner(fieldKey: string): string {
  return (
    `No custom field named "${fieldKey}" is defined for this station. ` +
    `Define it in Setup → Custom Fields, then re-run the report.`
  )
}

/**
 * Build the query-string portion of a `/api/staff/reports/...` request. Used
 * by the data-fetch helpers and the CSV/XML download URL builder so the two
 * stay in lock-step. Empty/undefined params are omitted.
 */
export function reportsQueryString(params: {
  from: string
  to: string
  channel?: string | null
  field?: string | null
  type?: string
  format?: string
}): string {
  const qs = new URLSearchParams()
  qs.set('from', params.from)
  qs.set('to', params.to)
  if (params.channel) qs.set('channel', params.channel)
  if (params.field) qs.set('field', params.field)
  if (params.type) qs.set('type', params.type)
  if (params.format) qs.set('format', params.format)
  return qs.toString()
}
