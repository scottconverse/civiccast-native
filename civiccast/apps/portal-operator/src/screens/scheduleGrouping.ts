// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Pure date-grouping helpers for ScheduleScreen, split out of the screen
// component so this module only exports non-component values (functions and
// types) and ScheduleScreen.tsx only exports the component itself --
// react-refresh/only-export-components requires that split, and mixing the
// two in one file is exactly the shape that broke fast refresh here. Kept in
// its own file (rather than inlined with an eslint-disable) so
// ScheduleScreen.test.tsx can unit-test the grouping logic directly, the way
// the beta-blocker regression tests below require.
import type { ScheduleItem } from '../types/schedule'

export type DayGroup = { key: string; day: Date; items: ScheduleItem[] }
export type GroupedSchedule = { groups: DayGroup[]; unreadable: ScheduleItem[] }

/**
 * Parse an air time off the wire, or return null.
 *
 * The value MUST be rejected before it reaches the Date constructor, not
 * after. `new Date(null)` does not yield an Invalid Date — it yields the Unix
 * epoch, so a null air time passes a `Number.isNaN(d.getTime())` check and
 * renders as a program scheduled for 31 Dec 1969. Silently wrong is worse
 * than visibly broken: nothing tells the operator that row is meaningless.
 * `scheduled_at` is typed `string`, but the type describes the contract, not
 * what a database column or an older station actually sends.
 */
export function parseAirTime(raw: unknown): Date | null {
  if (typeof raw !== 'string' || raw.trim() === '') return null
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return null
  return d
}

/**
 * Group schedule items by local day.
 *
 * A single item whose `scheduled_at` the browser cannot parse used to take
 * down this entire screen. `new Date(bad)` yields an Invalid Date, which
 * still produced a map key (`NaN-NaN-NaN`) and a stored `day`, and the
 * render then called `day.toISOString()` — which THROWS `RangeError: Invalid
 * time value` during render. The operator saw no toast, no inline error and
 * no network request; the drawer simply never closed, so scheduling anything
 * became impossible. Measured in the field 2026-08-14.
 *
 * So: unparseable rows are quarantined rather than grouped, and returned to
 * the caller so the screen can tell the operator that some items could not be
 * read instead of dying silently. One bad row must never cost the whole
 * screen.
 */
export function groupByDay(items: ScheduleItem[]): GroupedSchedule {
  const map = new Map<string, DayGroup>()
  const unreadable: ScheduleItem[] = []
  for (const it of items) {
    const d = parseAirTime(it.scheduled_at)
    if (d === null) {
      unreadable.push(it)
      continue
    }
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    const existing = map.get(key)
    if (existing) {
      existing.items.push(it)
    } else {
      const day = new Date(d)
      day.setHours(0, 0, 0, 0)
      map.set(key, { key, day, items: [it] })
    }
  }
  const groups = Array.from(map.values())
  groups.sort((a, b) => a.day.getTime() - b.day.getTime())
  for (const g of groups) {
    g.items.sort(
      (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
    )
  }
  return { groups, unreadable }
}
