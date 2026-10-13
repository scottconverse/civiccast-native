// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S21 RecordingScreen — pure formatters and helpers. Split out of the screen
// file so the screen module stays react-refresh-clean (components-only export,
// per the eslint-plugin-react-refresh convention used across this app).

import type {
  RecordingJob,
  RecordingSource,
  RecurrenceSpec,
} from '../api/client'
import {
  formatStationDateTimeLocal,
  formatStationInstant,
  nextStationOneShotFireTimes,
  nextStationWeeklyFireTimes,
} from '../lib/station-time'

export const LIVE_SOURCE_KINDS = ['sdi', 'hdmi', 'ndi'] as const

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Pretty source label: "SDI sdi-1" for live inputs, "RTSP rtsp://…" for
 *  network streams. Mirrors the "humanized" requirement from the spec. */
export function humanizeSource(source: RecordingSource): string {
  const kind = source.kind.toUpperCase()
  if ((LIVE_SOURCE_KINDS as readonly string[]).includes(source.kind)) {
    return source.input_id ? `${kind} ${source.input_id}` : kind
  }
  return source.uri ? `${kind} ${source.uri}` : kind
}

/** Pretty recurrence label: "One-shot 2026-06-20 19:00 UTC" or
 *  "Weekly Mon/Wed 19:00 UTC". */
export function humanizeRecurrence(rec: RecurrenceSpec, timeZone = 'UTC'): string {
  if (rec.kind === 'one_shot') {
    const local = formatStationDateTimeLocal(new Date(rec.start), timeZone)
    if (local) return `One-shot ${local} ${timeZone}`
    return `One-shot ${rec.start}`
  }
  const days = rec.weekdays
    .filter((d) => d >= 0 && d < 7)
    .map((d) => WEEKDAY_LABELS[d])
    .join('/')
  const recurrenceZone = rec.time_zone === 'station' ? timeZone : 'UTC'
  return `Weekly ${days || '(no days)'} ${rec.time_hhmm} ${recurrenceZone}`
}

/** Total-seconds → "HH:MM:SS". Negatives clamp to zero so we never render a
 *  literal "-01:00:00" by accident. */
export function formatDurationHMS(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

/** "HH:MM:SS" → seconds. Returns null on bad input. Accepts "H:MM:SS" or
 *  "HH:MM:SS" — leading zero on hours is optional but the minute / second
 *  fields must be two digits so we don't silently accept "1:5:0". */
export function parseDurationHMS(value: string): number | null {
  const trimmed = value.trim()
  const m = trimmed.match(/^(\d{1,3}):([0-5]\d):([0-5]\d)$/)
  if (!m) return null
  const h = Number(m[1])
  const mm = Number(m[2])
  const ss = Number(m[3])
  if (!Number.isFinite(h) || !Number.isFinite(mm) || !Number.isFinite(ss)) return null
  const total = h * 3600 + mm * 60 + ss
  if (total <= 0) return null
  return total
}

/** Bytes → "1.2 GB" / "850.0 MB" / "12.0 KB" / "0 B". Decimal SI shape (10^3)
 *  matches what most operator users expect on a disk-budget table. */
export function humanizeBytes(bytes: number): string {
  if (bytes <= 0 || !Number.isFinite(bytes)) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let i = 0
  while (value >= 1000 && i < units.length - 1) {
    value /= 1000
    i++
  }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** ISO-8601 UTC → local-time short string for the jobs table. We accept
 *  anything the browser's `Date` parser accepts; on parse failure we render
 *  the raw value so the operator can still see what came back. */
export function formatPlannedStart(isoString: string, timeZone = 'UTC'): string {
  if (!isoString) return '—'
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return isoString
  return formatStationInstant(d, timeZone)
}

/** Wall-clock time the capture job has actually run, separate from media
 * duration. A queued or prearmed job has no elapsed capture time yet. */
export function jobDuration(job: RecordingJob, now: Date = new Date()): string {
  if (!job.started_at) return '—'
  const endIso =
    job.ended_at ??
    (job.state === 'recording' || job.state === 'finalizing' ? now.toISOString() : null)
  if (!endIso) return '—'
  const start = new Date(job.started_at).getTime()
  const end = new Date(endIso).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  return formatDurationHMS(Math.max(0, Math.floor((end - start) / 1000)))
}

// --- UTC ↔ local time honesty helpers (UX-2 / UX-8) -----------------------
//
// Station-aware scheduling previews use the helpers below. The browser-local
// echo helpers remain exported for older callers that explicitly handle UTC.

/** Browser's local timezone short name (e.g. "PDT", "EST", "GMT+1"). Returns
 *  an empty string in environments where Intl is missing or partial. */
export function localTimezoneShortName(date: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, {
      timeZoneName: 'short',
    }).formatToParts(date)
    const tz = parts.find((p) => p.type === 'timeZoneName')
    return tz ? tz.value : ''
  } catch {
    return ''
  }
}

/** Format a Date in the operator's local zone as "YYYY-MM-DD HH:MM TZ" — used
 *  in the live UTC→local echo. Returns '' on invalid input. */
export function formatLocalEcho(date: Date): string {
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  const y = date.getFullYear()
  const mo = pad(date.getMonth() + 1)
  const d = pad(date.getDate())
  const h = pad(date.getHours())
  const mi = pad(date.getMinutes())
  const tz = localTimezoneShortName(date)
  return tz ? `${y}-${mo}-${d} ${h}:${mi} ${tz}` : `${y}-${mo}-${d} ${h}:${mi}`
}

/** Interpret a datetime-local value as UTC and format it in the browser zone.
 *  Returns '' for blank / malformed input. */
export function utcDateTimeLocalToLocalEcho(value: string): string {
  if (!value) return ''
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return ''
  const iso = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00Z`
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return formatLocalEcho(d)
}

/** UTC "HH:MM" → local-time echo for the next fire of that wall-clock UTC
 *  time relative to `now`. Returns '' for malformed input. */
export function utcHHMMToLocalEcho(value: string, now: Date = new Date()): string {
  const m = value.trim().match(/^([01]\d|2[0-3]):([0-5]\d)$/)
  if (!m) return ''
  const fire = new Date(now)
  fire.setUTCHours(Number(m[1]), Number(m[2]), 0, 0)
  // If the time has already passed UTC-today, show tomorrow's instance —
  // that's the wall-clock the operator would actually see fire next.
  if (fire.getTime() <= now.getTime()) fire.setUTCDate(fire.getUTCDate() + 1)
  return formatLocalEcho(fire)
}

/** Compute the next N fires. `weekdays` are Mon=0..Sun=6; `timeHHMM` is a
 *  wall clock in `timeZone` (UTC by default). Returned Dates are instants. */
export function nextWeeklyFireTimes(
  weekdays: number[],
  timeHHMM: string,
  count = 3,
  now: Date = new Date(),
  timeZone = 'UTC',
): Date[] {
  return nextStationWeeklyFireTimes(weekdays, timeHHMM, timeZone, count, now)
}

/** Resolve a datetime-local wall clock in `timeZone` and return its next-fire
 *  preview, if still upcoming. Returns at most 1 date. */
export function nextOneShotFireTimes(
  value: string,
  now: Date = new Date(),
  timeZone = 'UTC',
): Date[] {
  return nextStationOneShotFireTimes(value, timeZone, now)
}

/** Format an instant in UTC and in the selected station timezone. */
export function formatFirePreview(date: Date, timeZone = 'UTC'): string {
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  const utc =
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    ` ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  const station = formatStationInstant(date, timeZone, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  })
  return station ? `${utc} · ${station} (${timeZone})` : utc
}
