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
export function humanizeRecurrence(rec: RecurrenceSpec): string {
  if (rec.kind === 'one_shot') {
    // The backend stores ISO-8601 in UTC. We pretty-print as
    // "YYYY-MM-DD HH:MM UTC" (no seconds, no timezone juggling) so the
    // operator sees the same value across machines.
    const m = rec.start.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
    if (m) return `One-shot ${m[1]} ${m[2]} UTC`
    return `One-shot ${rec.start}`
  }
  const days = rec.weekdays
    .filter((d) => d >= 0 && d < 7)
    .map((d) => WEEKDAY_LABELS[d])
    .join('/')
  return `Weekly ${days || '(no days)'} ${rec.time_hhmm} UTC`
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
export function formatPlannedStart(isoString: string): string {
  if (!isoString) return '—'
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return isoString
  return d.toLocaleString()
}

/** Job duration: prefer real start/end, fall back to planned span. Returns
 *  HH:MM:SS for the table. */
export function jobDuration(job: RecordingJob): string {
  const startIso = job.started_at ?? job.planned_start
  const endIso = job.ended_at ?? job.planned_end
  if (!startIso || !endIso) return '—'
  const start = new Date(startIso).getTime()
  const end = new Date(endIso).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  return formatDurationHMS(Math.max(0, Math.floor((end - start) / 1000)))
}

// --- UTC ↔ local time honesty helpers (UX-2 / UX-8) -----------------------
//
// The schedule form stores wall-clock UTC values (datetime-local for one-shot,
// "HH:MM" for weekly). The browser renders datetime-local in the operator's
// local zone by default — so a label that says "(UTC)" next to a control the
// browser is showing in PDT will silently book the recording at the wrong
// wall-clock time. These helpers compute a live local-time echo + the next
// three fire times so the operator can sanity-check before saving.
//
// All math is timezone-aware via `Intl.DateTimeFormat`; we don't ship a tz
// library. The "local" zone is the runtime zone of the operator's browser.

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

/** UTC "YYYY-MM-DDTHH:MM" (the datetime-local input value, treated as UTC) →
 *  formatted local echo. Returns '' for blank / malformed input. */
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

/** Compute the next N fire times for a weekly schedule. `weekdays` are
 *  Mon=0..Sun=6 (matches the backend / form convention). `timeHHMM` is the
 *  wall-clock UTC time. Returns Dates anchored to UTC. */
export function nextWeeklyFireTimes(
  weekdays: number[],
  timeHHMM: string,
  count = 3,
  now: Date = new Date(),
): Date[] {
  const tm = timeHHMM.trim().match(/^([01]\d|2[0-3]):([0-5]\d)$/)
  if (!tm) return []
  const days = Array.from(new Set(weekdays.filter((d) => d >= 0 && d < 7))).sort()
  if (days.length === 0) return []
  const hh = Number(tm[1])
  const mm = Number(tm[2])
  const out: Date[] = []
  // Walk forward up to 14 UTC-days; a weekly schedule fires at least once
  // per 7-day window, so 14 is a safe outer bound for the first three.
  const cursor = new Date(now)
  cursor.setUTCSeconds(0, 0)
  for (let i = 0; i < 14 && out.length < count; i++) {
    const day = new Date(cursor)
    day.setUTCDate(day.getUTCDate() + i)
    day.setUTCHours(hh, mm, 0, 0)
    // Convert UTC day-of-week (0=Sun..6=Sat) to Mon=0..Sun=6.
    const utcDow = day.getUTCDay() // 0..6, Sun=0
    const monFirst = (utcDow + 6) % 7
    if (!days.includes(monFirst)) continue
    if (day.getTime() <= now.getTime()) continue
    out.push(day)
  }
  return out
}

/** UTC "YYYY-MM-DDTHH:MM" + duration_seconds → next-fire previews for a
 *  one-shot schedule. Returns at most 1 date (one-shot fires once). */
export function nextOneShotFireTimes(value: string, now: Date = new Date()): Date[] {
  if (!value) return []
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return []
  const d = new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00Z`)
  if (Number.isNaN(d.getTime())) return []
  if (d.getTime() <= now.getTime()) return []
  return [d]
}

/** Format a Date for the next-fire preview: "UTC YYYY-MM-DD HH:MM · local
 *  YYYY-MM-DD HH:MM TZ". */
export function formatFirePreview(date: Date): string {
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => n.toString().padStart(2, '0')
  const utc =
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}` +
    ` ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  const local = formatLocalEcho(date)
  return local ? `${utc} · ${local}` : utc
}
