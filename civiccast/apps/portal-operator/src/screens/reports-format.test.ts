// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import {
  fieldNotFoundBanner,
  formatHms,
  formatHours,
  parseFieldMapText,
  reportsQueryString,
  stringifyFieldMap,
} from './reports-format'

describe('formatHms', () => {
  it('renders zero and bad values as 0s', () => {
    expect(formatHms(0)).toBe('0s')
    expect(formatHms(-1)).toBe('0s')
    expect(formatHms(Number.NaN)).toBe('0s')
    expect(formatHms(Number.POSITIVE_INFINITY)).toBe('0s')
  })
  it('renders seconds-only when under a minute', () => {
    expect(formatHms(7)).toBe('7s')
  })
  it('renders minutes + seconds when under an hour', () => {
    expect(formatHms(65)).toBe('1m 5s')
  })
  it('renders h + m + s above the hour mark', () => {
    expect(formatHms(3725)).toBe('1h 2m 5s')
  })
  it('keeps the 0m component visible when seconds carry past the hour boundary', () => {
    expect(formatHms(3605)).toBe('1h 0m 5s')
  })
})

describe('formatHours', () => {
  it('clamps non-finite + non-positive to 0', () => {
    expect(formatHours(0)).toBe('0.00h')
    expect(formatHours(-1)).toBe('0.00h')
    expect(formatHours(Number.NaN)).toBe('0.00h')
  })
  it('renders to two decimals', () => {
    expect(formatHours(12.3456)).toBe('12.35h')
    expect(formatHours(0.5)).toBe('0.50h')
  })
})

describe('parseFieldMapText', () => {
  it('returns an empty record for empty input', () => {
    expect(parseFieldMapText('')).toEqual({})
  })
  it('parses simple key=value lines', () => {
    const out = parseFieldMapText('category=cat\nrating=tv-pg')
    expect(out).toEqual({ category: 'cat', rating: 'tv-pg' })
  })
  it('trims whitespace and ignores blank + comment lines', () => {
    const out = parseFieldMapText('  # comment\n\n  category = cat \nrating= tv-pg')
    expect(out).toEqual({ category: 'cat', rating: 'tv-pg' })
  })
  it('drops malformed lines without crashing', () => {
    const out = parseFieldMapText('no-equals-sign\n=bad\nok=fine')
    expect(out).toEqual({ ok: 'fine' })
  })
  it('preserves empty values (= with nothing after)', () => {
    expect(parseFieldMapText('drop=')).toEqual({ drop: '' })
  })
})

describe('stringifyFieldMap', () => {
  it('round-trips with parseFieldMapText (after sort)', () => {
    const src = { rating: 'tv-pg', category: 'cat' }
    const text = stringifyFieldMap(src)
    expect(text).toBe('category=cat\nrating=tv-pg')
    expect(parseFieldMapText(text)).toEqual(src)
  })
  it('handles null/undefined as empty', () => {
    expect(stringifyFieldMap(null)).toBe('')
    expect(stringifyFieldMap(undefined)).toBe('')
  })
})

describe('fieldNotFoundBanner', () => {
  it('names the missing field and points at Setup', () => {
    const copy = fieldNotFoundBanner('category')
    expect(copy).toContain('"category"')
    expect(copy).toContain('Setup → Custom Fields')
  })
})

describe('reportsQueryString', () => {
  it('always includes from + to', () => {
    const qs = reportsQueryString({ from: '2026-06-01T00:00:00Z', to: '2026-06-02T00:00:00Z' })
    expect(qs).toContain('from=2026-06-01T00%3A00%3A00Z')
    expect(qs).toContain('to=2026-06-02T00%3A00%3A00Z')
  })
  it('omits absent optional params', () => {
    const qs = reportsQueryString({ from: 'a', to: 'b' })
    expect(qs).not.toContain('channel')
    expect(qs).not.toContain('field')
    expect(qs).not.toContain('type')
    expect(qs).not.toContain('format')
  })
  it('includes channel + field + type + format when present', () => {
    const qs = reportsQueryString({
      from: 'a',
      to: 'b',
      channel: 'pub-1',
      field: 'category',
      type: 'as-run',
      format: 'csv',
    })
    expect(qs).toContain('channel=pub-1')
    expect(qs).toContain('field=category')
    expect(qs).toContain('type=as-run')
    expect(qs).toContain('format=csv')
  })
})
