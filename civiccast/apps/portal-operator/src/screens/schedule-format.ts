import type { ScheduleItem } from '../types/schedule'
import { formatStationInstant } from '../lib/station-time'
import { formatHms } from './reports-format'

export function fmtRangeLabel(item: ScheduleItem, timeZone: string): string {
  const start = new Date(item.scheduled_at)
  const startStr = formatStationInstant(start, timeZone, { hour: 'numeric', minute: '2-digit', second: '2-digit' })
  if (!item.duration_seconds || item.mode === 'embargo') return startStr
  const end = new Date(start.getTime() + item.duration_seconds * 1000)
  return `${startStr} – ${formatStationInstant(end, timeZone, { hour: 'numeric', minute: '2-digit',
    second: '2-digit' })} (${formatHms(item.duration_seconds)})`
}
