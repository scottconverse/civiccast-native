// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

export type StationDateParts = { year: number; month: number; day: number; hour: number; minute: number; second: number }
type WallParts = StationDateParts

/** The backend maps the unset `local` sentinel and invalid names to UTC. */
export function effectiveStationTimeZone(value?: string | null): string {
  if (!value || value === 'local') return 'UTC'
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value })
    return value
  } catch {
    return 'UTC'
  }
}

function partsAt(instant: Date, timeZone: string): WallParts | null {
  if (Number.isNaN(instant.getTime())) return null
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(instant)
    const value = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value)
    const result = {
      year: value('year'), month: value('month'), day: value('day'),
      hour: value('hour'), minute: value('minute'), second: value('second'),
    }
    return Object.values(result).every(Number.isFinite) ? result : null
  } catch {
    return null
  }
}

export function stationDateParts(instant: Date, timeZone: string): StationDateParts | null {
  return partsAt(instant, timeZone)
}

function sameWallClock(a: WallParts, b: WallParts): boolean {
  return a.year === b.year && a.month === b.month && a.day === b.day &&
    a.hour === b.hour && a.minute === b.minute && a.second === b.second
}

/** Resolve a datetime-local string in a station zone. Gaps return null;
 * repeated clocks choose the earlier instant, matching the scheduler. */
export function stationWallClockToDate(value: string, timeZone: string): Date | null {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return null
  const requested: WallParts = {
    year: Number(match[1]), month: Number(match[2]), day: Number(match[3]),
    hour: Number(match[4]), minute: Number(match[5]), second: Number(match[6] ?? 0),
  }
  const wallAsUtc = Date.UTC(requested.year, requested.month - 1, requested.day, requested.hour, requested.minute, requested.second)
  const check = new Date(wallAsUtc)
  if (check.getUTCFullYear() !== requested.year || check.getUTCMonth() + 1 !== requested.month ||
      check.getUTCDate() !== requested.day || requested.hour > 23 || requested.minute > 59 || requested.second > 59) return null

  const offsets = new Set<number>()
  // The offsets surrounding the requested wall clock include both sides of
  // ordinary DST folds and gaps. Sampling a two-day window also handles
  // zones whose transition occurs at midnight.
  for (let hours = -48; hours <= 48; hours += 3) {
    const sample = new Date(wallAsUtc + hours * 3_600_000)
    const local = partsAt(sample, timeZone)
    if (local) {
      const localAsUtc = Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute, local.second)
      offsets.add(localAsUtc - Math.floor(sample.getTime() / 1000) * 1000)
    }
  }
  const matches: number[] = []
  for (const offset of offsets) {
    const instant = new Date(wallAsUtc - offset)
    const local = partsAt(instant, timeZone)
    if (local && sameWallClock(local, requested)) matches.push(instant.getTime())
  }
  return matches.length ? new Date(Math.min(...matches)) : null
}

/** Render an instant as the value expected by datetime-local in a station zone. */
export function dateToStationDateTimeLocal(instant: Date, timeZone: string): string {
  const p = partsAt(instant, timeZone)
  if (!p) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}${p.second ? `:${pad(p.second)}` : ''}`
}

export function formatStationInstant(
  instant: Date,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
): string {
  if (Number.isNaN(instant.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone }).format(instant)
  } catch {
    return instant.toISOString()
  }
}

export function formatStationDateTimeLocal(instant: Date, timeZone: string): string {
  const p = partsAt(instant, timeZone)
  if (!p) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}`
}

export function stationDateKey(instant: Date, timeZone: string): string {
  const p = partsAt(instant, timeZone)
  if (!p) return ''
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`
}

export function dateFromStationDateKey(key: string): Date {
  const match = key.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return match
    ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
    : new Date(Number.NaN)
}

export function formatStationEcho(instant: Date, timeZone: string): string {
  if (Number.isNaN(instant.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    }).format(instant)
  } catch {
    return formatStationDateTimeLocal(instant, 'UTC')
  }
}

export function nextStationWeeklyFireTimes(
  weekdays: number[], timeHHMM: string, timeZone: string, count = 3, now = new Date(),
): Date[] {
  const time = timeHHMM.match(/^([01]\d|2[0-3]):([0-5]\d)$/)
  const today = partsAt(now, timeZone)
  const allowed = new Set(weekdays.filter((day) => day >= 0 && day < 7))
  if (!time || !today || !allowed.size || count <= 0) return []
  const out: Date[] = []
  const firstDay = Date.UTC(today.year, today.month - 1, today.day)
  for (let offset = 0; offset < 30 && out.length < count; offset++) {
    const day = new Date(firstDay + offset * 86_400_000)
    const mondayFirst = (day.getUTCDay() + 6) % 7
    if (!allowed.has(mondayFirst)) continue
    const date = `${day.getUTCFullYear()}-${String(day.getUTCMonth() + 1).padStart(2, '0')}-${String(day.getUTCDate()).padStart(2, '0')}`
    const candidate = stationWallClockToDate(`${date}T${time[1]}:${time[2]}`, timeZone)
    if (candidate && candidate.getTime() > now.getTime()) out.push(candidate)
  }
  return out
}

export function nextStationOneShotFireTimes(value: string, timeZone: string, now = new Date()): Date[] {
  const date = stationWallClockToDate(value, timeZone)
  return date && date.getTime() > now.getTime() ? [date] : []
}
