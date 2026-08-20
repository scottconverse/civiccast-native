// Display helpers for the auto-schedule console (S18 slice 6). Pure functions
// only — kept out of the screen component file so eslint's
// react-hooks/only-export-components rule stays satisfied.

import type { SlotPreview } from '../types/api.generated'

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

const MINUTES_PER_DAY = 24 * 60

/** Operator-facing label for a rule's pick strategy. */
export function pickStrategyLabel(strategy: string | undefined): string {
  switch (strategy) {
    case 'top_result':
      return 'First match'
    case 'random_result':
      return 'Random'
    case 'newest':
      return 'Newest first'
    default:
      return strategy ?? 'Newest first'
  }
}

/** Plain-English label for what a previewed slot would do. */
export function slotActionLabel(action: SlotPreview['action']): string {
  switch (action) {
    case 'fill':
      return 'Will air'
    case 'occupied':
      return 'Already scheduled'
    case 'no_asset':
      return 'No eligible video'
    case 'unplayable':
      return 'No usable duration'
  }
}

/** Tone token for coloring a previewed slot's status pill. */
export function slotActionTone(action: SlotPreview['action']): 'ok' | 'muted' | 'warn' {
  switch (action) {
    case 'fill':
      return 'ok'
    case 'occupied':
      return 'muted'
    case 'no_asset':
    case 'unplayable':
      return 'warn'
  }
}

/** A minute-of-day (0..1440) as wall-clock "HH:MM" (1440 → "24:00"). */
export function minuteToHHMM(minuteOfDay: number): string {
  const clamped = Math.max(0, Math.min(Math.trunc(minuteOfDay), MINUTES_PER_DAY))
  const hours = Math.floor(clamped / 60)
  const minutes = clamped % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

/** Parse a wall-clock "HH:MM" into a minute-of-day. "24:00" → 1440. */
export function hhmmToMinute(value: string): number {
  const [hoursRaw, minutesRaw] = value.split(':')
  const hours = Number.parseInt(hoursRaw, 10)
  const minutes = Number.parseInt(minutesRaw, 10)
  return (Number.isNaN(hours) ? 0 : hours) * 60 + (Number.isNaN(minutes) ? 0 : minutes)
}

/** A weekday list (0=Mon..6=Sun) as "Mon, Wed, Fri" (sorted). */
export function formatDays(days: readonly number[]): string {
  if (!days.length) return 'No days'
  return [...days]
    .sort((a, b) => a - b)
    .map((day) => WEEKDAY_LABELS[day] ?? `?${day}`)
    .join(', ')
}
