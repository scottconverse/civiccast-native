// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Pure formatting + parsing helpers for the S24 Underwriting screen. Kept
// separate from the React surface so they can be unit-tested without
// rendering. Mirrors the shape of `reports-format.ts`.

/**
 * Parse a free-text channels input (commas or newlines) into a clean
 * deduplicated + alphabetically-sorted list of channel IDs. Used by the
 * flight create/edit form, where the operator types `pub-1, gov-1` and the
 * server stores `["gov-1", "pub-1"]`.
 *
 * Empty/blank entries are dropped. Whitespace is trimmed from each ID. The
 * sort gives a deterministic round-trip with `stringifyChannels` regardless
 * of input order, so an Edit-then-Save with no real changes does not appear
 * to the server as an update.
 */
export function parseChannelsText(s: string): string[] {
  if (!s) return []
  const parts = s.split(/[,\n\r]+/)
  const seen = new Set<string>()
  for (const raw of parts) {
    const trimmed = raw.trim()
    if (trimmed.length === 0) continue
    seen.add(trimmed)
  }
  return Array.from(seen).sort()
}

/**
 * Render a channels list back as a comma-separated string for the textarea/
 * input value. Sorted by `parseChannelsText` already; we accept whatever the
 * server returns and emit a stable order so the form prefills consistently.
 */
export function stringifyChannels(channels: string[] | undefined | null): string {
  if (!channels || channels.length === 0) return ''
  return [...channels].sort().join(', ')
}

/**
 * Format a duration in seconds as "Hh Mm Ss" — same shape as
 * `reports-format.ts::formatHms`. Used on the affidavit totals row so the
 * operator sees a human-readable "1h 23m 4s" instead of raw seconds. Bad
 * inputs clamp to "0s" so a row never crashes the render.
 */
export function formatDuration(totalSeconds: number): string {
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
 * The verbatim FCC 47 CFR 73.503 reminder text that must appear under the
 * `fcc_compliant_ack` checkbox on the spot form (DC-5). Lifted out of JSX so
 * the test can assert exact text and so we have one canonical copy if the
 * spec text is ever revised.
 */
export const FCC_73_503_REMINDER =
  'Per 47 CFR 73.503, underwriting acknowledgments may identify the sponsor ' +
  'by name, logo, location, and a value-neutral description only. Calls to ' +
  'action, prices, comparative or qualitative claims, and promotional ' +
  'language are not permitted. Tick this box only after you have reviewed ' +
  'the spot and confirmed it meets these rules. Content is not auto-checked ' +
  '— your attestation is the editorial gate.'

/**
 * Build the query-string for an affidavit request — exact match for the
 * server's `from`/`to`/`underwriter` (and optionally `format`) params so the
 * fetch helper and the `<a download>` URL stay in lock-step.
 *
 * Underscore-prefixed because the format module owns the QS shape but the
 * screen exclusively reaches it via `affidavitExportUrl()` in the client.
 */
export function _affidavitQueryString(params: {
  underwriter: string
  from: string
  to: string
  format?: 'csv' | 'xml' | 'pdf'
}): string {
  const qs = new URLSearchParams()
  qs.set('underwriter', params.underwriter)
  qs.set('from', params.from)
  qs.set('to', params.to)
  if (params.format) qs.set('format', params.format)
  return qs.toString()
}
