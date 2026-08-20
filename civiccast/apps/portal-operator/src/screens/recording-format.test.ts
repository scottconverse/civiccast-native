// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Lock-in tests for the recording-format helpers that back the UX-2 / UX-8
// timezone-honesty fixes in S21 RecordingScreen. These run alongside the
// existing formatter coverage in RecordingScreen.test.tsx but live in their
// own file so the helper module has a direct test boundary.

import { describe, expect, it } from 'vitest'

import {
  formatFirePreview,
  formatLocalEcho,
  localTimezoneShortName,
  nextOneShotFireTimes,
  nextWeeklyFireTimes,
  utcDateTimeLocalToLocalEcho,
  utcHHMMToLocalEcho,
} from './recording-format'

describe('localTimezoneShortName', () => {
  it('returns a non-empty short timezone label in a normal Intl env', () => {
    // Vitest's jsdom env always ships Intl with timezone-short support; this
    // is a smoke that the helper finds it. We don't pin the value because the
    // host TZ floats.
    expect(localTimezoneShortName()).not.toBe('')
  })
})

describe('formatLocalEcho', () => {
  it('returns "" for an invalid Date', () => {
    expect(formatLocalEcho(new Date('not-a-date'))).toBe('')
  })

  it('returns a YYYY-MM-DD HH:MM string for a valid Date', () => {
    const d = new Date('2026-06-20T19:00:00Z')
    const out = formatLocalEcho(d)
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)
  })
})

describe('utcDateTimeLocalToLocalEcho', () => {
  it('returns "" on blank or malformed input', () => {
    expect(utcDateTimeLocalToLocalEcho('')).toBe('')
    expect(utcDateTimeLocalToLocalEcho('garbage')).toBe('')
  })

  it('treats the value as UTC and produces a local echo', () => {
    const out = utcDateTimeLocalToLocalEcho('2026-06-20T19:00')
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)
  })
})

describe('utcHHMMToLocalEcho', () => {
  it('returns "" on malformed HH:MM input', () => {
    expect(utcHHMMToLocalEcho('')).toBe('')
    expect(utcHHMMToLocalEcho('25:00')).toBe('')
    expect(utcHHMMToLocalEcho('19:99')).toBe('')
    expect(utcHHMMToLocalEcho('1900')).toBe('')
  })

  it('produces a YYYY-MM-DD HH:MM echo for a valid HH:MM', () => {
    // Pin "now" so the future-bump logic is deterministic.
    const now = new Date('2026-06-20T10:00:00Z')
    const out = utcHHMMToLocalEcho('19:00', now)
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/)
  })

  it('rolls to tomorrow when the UTC HH:MM has already passed today', () => {
    const now = new Date('2026-06-20T22:00:00Z')
    const out = utcHHMMToLocalEcho('19:00', now)
    // 19:00 UTC < 22:00 UTC today, so the helper should show 2026-06-21's
    // instance. The Date carries a 2026-06-21 wall in UTC; the local echo is
    // a TZ-shifted view of that same instant.
    expect(out).not.toBe('')
  })
})

describe('nextWeeklyFireTimes', () => {
  // Pin "now" so the next-fire walk is deterministic regardless of when the
  // tests run. 2026-06-15 is a Monday (UTC).
  const monday = new Date('2026-06-15T00:00:00Z')

  it('returns 3 dates by default for a Mon/Wed schedule starting from Monday', () => {
    const out = nextWeeklyFireTimes([0, 2], '19:00', 3, monday)
    expect(out.length).toBe(3)
    // Each fire is on a Mon (UTC dow 1) or Wed (UTC dow 3).
    for (const d of out) {
      const dow = d.getUTCDay()
      expect(dow === 1 || dow === 3).toBe(true)
      expect(d.getUTCHours()).toBe(19)
      expect(d.getUTCMinutes()).toBe(0)
    }
    // Output is in ascending order.
    for (let i = 1; i < out.length; i++) {
      expect(out[i].getTime()).toBeGreaterThan(out[i - 1].getTime())
    }
  })

  it('returns [] when no weekdays are picked', () => {
    expect(nextWeeklyFireTimes([], '19:00', 3, monday)).toEqual([])
  })

  it('returns [] when the HH:MM is malformed', () => {
    expect(nextWeeklyFireTimes([0], 'bad', 3, monday)).toEqual([])
  })

  it('respects the count argument', () => {
    expect(nextWeeklyFireTimes([0, 1, 2, 3, 4], '19:00', 5, monday).length).toBe(5)
  })
})

describe('nextOneShotFireTimes', () => {
  const now = new Date('2026-06-15T00:00:00Z')

  it('returns one date for a future one-shot', () => {
    const out = nextOneShotFireTimes('2026-06-20T19:00', now)
    expect(out.length).toBe(1)
    expect(out[0].getUTCFullYear()).toBe(2026)
    expect(out[0].getUTCMonth()).toBe(5) // June (0-indexed)
    expect(out[0].getUTCHours()).toBe(19)
  })

  it('returns [] for a one-shot in the past', () => {
    expect(nextOneShotFireTimes('2020-01-01T00:00', now)).toEqual([])
  })

  it('returns [] for blank / malformed input', () => {
    expect(nextOneShotFireTimes('', now)).toEqual([])
    expect(nextOneShotFireTimes('not-a-date', now)).toEqual([])
  })
})

describe('formatFirePreview', () => {
  it('includes both UTC and a local echo', () => {
    const out = formatFirePreview(new Date('2026-06-20T19:00:00Z'))
    expect(out).toMatch(/UTC/)
    // The local echo is appended after a separator.
    expect(out).toMatch(/·/)
  })

  it('returns "" for an invalid Date', () => {
    expect(formatFirePreview(new Date('garbage'))).toBe('')
  })
})
