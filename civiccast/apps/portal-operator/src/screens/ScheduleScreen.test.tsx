// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Beta blocker (LPM native beta, 2026-08-14): a single schedule row whose
// `scheduled_at` the browser could not parse blanked the entire Schedule
// screen. `new Date(bad)` yields an Invalid Date; the day-grouping key came
// out `NaN-NaN-NaN` so the row still produced a group, and the list render
// then called `day.toISOString()` for the React key — which THROWS
// `RangeError: Invalid time value`. The throw happened during render, so
// there was no toast, no error boundary message and no failed request to
// point at. The screen simply went blank.
//
// The contract these tests pin: unreadable rows are quarantined and
// reported, every returned group carries a VALID Date plus a pre-computed
// stable key, and no readable row is ever lost because of a bad neighbour.
import { describe, expect, it } from 'vitest'

import { groupByDay } from './scheduleGrouping'
import type { ScheduleItem } from '../types/schedule'

const item = (id: string, scheduledAt: unknown): ScheduleItem =>
  ({
    id,
    asset_id: `asset-${id}`,
    channel_id: 'government',
    mode: 'premiere',
    state: 'scheduled',
    scheduled_at: scheduledAt,
    duration_seconds: 1800,
  }) as unknown as ScheduleItem

describe('groupByDay unreadable scheduled_at', () => {
  // Every shape that has actually reached a browser: absent column, SQL
  // NULL over JSON, an empty string from a partially-filled form, and a
  // free-text value.
  const badValues: Array<[string, unknown]> = [
    ['null', null],
    ['undefined', undefined],
    ['empty string', ''],
    ['free text', 'not-a-date'],
    ['half a date', '2026-13-45T99:99:99Z'],
  ]

  for (const [label, bad] of badValues) {
    it(`does not throw on ${label}`, () => {
      expect(() => groupByDay([item('bad', bad)])).not.toThrow()
    })

    it(`quarantines ${label} instead of grouping it`, () => {
      const { groups, unreadable } = groupByDay([item('bad', bad)])
      expect(groups).toHaveLength(0)
      expect(unreadable.map((r) => r.id)).toEqual(['bad'])
    })
  }

  it('keeps every readable row when a bad row sits beside it', () => {
    const { groups, unreadable } = groupByDay([
      item('good-1', '2026-08-20T18:00:00Z'),
      item('bad', null),
      item('good-2', '2026-08-21T18:00:00Z'),
    ])
    expect(unreadable.map((r) => r.id)).toEqual(['bad'])
    const kept = groups.flatMap((g) => g.items.map((i) => i.id))
    expect(kept).toEqual(['good-1', 'good-2'])
  })

  it('gives every group a valid Date and a usable React key', () => {
    const { groups } = groupByDay([
      item('bad', 'not-a-date'),
      item('good', '2026-08-20T18:00:00Z'),
    ])
    for (const g of groups) {
      // This is the exact property the list render depended on and that
      // the pre-fix code violated.
      expect(Number.isNaN(g.day.getTime())).toBe(false)
      expect(() => g.day.toISOString()).not.toThrow()
      expect(typeof g.key).toBe('string')
      expect(g.key.length).toBeGreaterThan(0)
      expect(g.key).not.toContain('NaN')
    }
  })

  it('returns nothing to render and nothing to warn about for an empty schedule', () => {
    const { groups, unreadable } = groupByDay([])
    expect(groups).toHaveLength(0)
    expect(unreadable).toHaveLength(0)
  })
})

describe('groupByDay ordering', () => {
  it('orders days oldest first and orders items within a day', () => {
    const { groups } = groupByDay([
      item('later-day', '2026-08-21T18:00:00Z'),
      item('early-second', '2026-08-20T20:00:00Z'),
      item('early-first', '2026-08-20T18:00:00Z'),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0].items.map((i) => i.id)).toEqual([
      'early-first',
      'early-second',
    ])
    expect(groups[1].items.map((i) => i.id)).toEqual(['later-day'])
    expect(groups[0].day.getTime()).toBeLessThan(groups[1].day.getTime())
  })

  it('gives two items on the same day one group with a shared key', () => {
    const { groups } = groupByDay([
      item('a', '2026-08-20T01:00:00Z'),
      item('b', '2026-08-20T23:00:00Z'),
    ])
    // Both instants land on the same LOCAL day for the runner's timezone
    // offsets we care about; assert the invariant rather than a count that
    // a timezone could flip.
    const keys = new Set(groups.map((g) => g.key))
    expect(keys.size).toBe(groups.length)
    expect(groups.flatMap((g) => g.items).map((i) => i.id).sort()).toEqual([
      'a',
      'b',
    ])
  })
})
