// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Pure formatting helpers for the S25 Agendas screen. Kept separate from the
// React surfaces so they can be unit-tested without rendering.

/**
 * Format a video timecode (in seconds) as zero-padded "HH:MM:SS" so a column
 * of timecodes lines up vertically. NULL / undefined / non-finite values yield
 * the em-dash placeholder used throughout the operator console.
 *
 * Distinct from `formatHms` in `reports-format.ts` (which renders "1h 2m 5s"
 * for total-airtime cells). The agenda editor wants a time-of-tape style
 * stamp because the operator reads it next to a video player.
 */
export function formatTimecode(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

/**
 * Lowercase a string and squash everything not in [a-z0-9_-] to a single
 * hyphen, trimming leading/trailing hyphens. Used to mint a fall-back slug
 * from a human-typed agenda or asset identifier.
 */
export function slugify(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * Returns true when the given URL string is plausibly an http(s):// URL. The
 * pattern is intentionally loose — the input also has an HTML5 `pattern=`
 * hint on the `<input type="url">` element. We do not block submit on a bad
 * URL because the operator can always paste a relative document path later;
 * the server stores whatever was sent. NULL / empty is treated as OK (the
 * field is optional).
 */
export function isPlausibleHttpUrl(value: string | null | undefined): boolean {
  if (value == null) return true
  const trimmed = value.trim()
  if (trimmed.length === 0) return true
  return /^https?:\/\/\S+$/i.test(trimmed)
}
