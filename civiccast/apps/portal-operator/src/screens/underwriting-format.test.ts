// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import {
  FCC_73_503_REMINDER,
  _affidavitQueryString,
  formatDuration,
  parseChannelsText,
  stringifyChannels,
} from './underwriting-format'

describe('parseChannelsText', () => {
  it('returns [] for empty input', () => {
    expect(parseChannelsText('')).toEqual([])
    expect(parseChannelsText('   ')).toEqual([])
    expect(parseChannelsText(',,,')).toEqual([])
  })

  it('splits on commas and newlines, trims, drops blanks', () => {
    expect(parseChannelsText('pub-1, gov-1\n edu-1 ,, pub-1')).toEqual(['edu-1', 'gov-1', 'pub-1'])
  })

  it('dedupes (same id repeated)', () => {
    expect(parseChannelsText('a, a, a, b')).toEqual(['a', 'b'])
  })

  it('sorts alphabetically so round-tripping is stable', () => {
    expect(parseChannelsText('zeta, alpha, mu')).toEqual(['alpha', 'mu', 'zeta'])
  })
})

describe('stringifyChannels', () => {
  it('emits empty string for nullish or empty', () => {
    expect(stringifyChannels(undefined)).toBe('')
    expect(stringifyChannels(null)).toBe('')
    expect(stringifyChannels([])).toBe('')
  })

  it('renders sorted comma-separated list', () => {
    expect(stringifyChannels(['zeta', 'alpha', 'mu'])).toBe('alpha, mu, zeta')
  })

  it('round-trips with parseChannelsText', () => {
    const parsed = parseChannelsText(' pub-1, gov-1 ')
    expect(parseChannelsText(stringifyChannels(parsed))).toEqual(parsed)
  })
})

describe('formatDuration', () => {
  it('clamps non-finite / non-positive to "0s"', () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(-5)).toBe('0s')
    expect(formatDuration(Number.NaN)).toBe('0s')
    expect(formatDuration(Number.POSITIVE_INFINITY)).toBe('0s')
  })

  it('renders seconds only under a minute', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('renders minutes + seconds under an hour', () => {
    expect(formatDuration(125)).toBe('2m 5s')
  })

  it('renders hours, minutes, and seconds at or above an hour', () => {
    // 1h 2m 5s = 3725s
    expect(formatDuration(3725)).toBe('1h 2m 5s')
    // 2h 0m 0s = 7200s — minutes must still appear when hours present
    expect(formatDuration(7200)).toBe('2h 0m 0s')
  })

  it('floors fractional seconds (matches reports-format.formatHms)', () => {
    expect(formatDuration(125.9)).toBe('2m 5s')
  })
})

describe('FCC_73_503_REMINDER', () => {
  it('cites 47 CFR 73.503 verbatim', () => {
    expect(FCC_73_503_REMINDER).toContain('47 CFR 73.503')
  })

  it('lists the sponsor-ID-only fields and the prohibited categories', () => {
    expect(FCC_73_503_REMINDER).toContain('name, logo, location')
    expect(FCC_73_503_REMINDER).toContain('value-neutral description')
    expect(FCC_73_503_REMINDER).toContain('Calls to action')
    expect(FCC_73_503_REMINDER).toContain('prices')
    expect(FCC_73_503_REMINDER).toContain('comparative or qualitative claims')
    expect(FCC_73_503_REMINDER).toContain('promotional')
  })

  it('makes the attestation the editorial gate, not auto-checked', () => {
    expect(FCC_73_503_REMINDER).toContain('not auto-checked')
    expect(FCC_73_503_REMINDER).toContain('editorial gate')
  })
})

describe('_affidavitQueryString', () => {
  it('emits underwriter, from, to (in that order) and url-encodes', () => {
    const qs = _affidavitQueryString({
      underwriter: 'Acme & Sons',
      from: '2026-06-01',
      to: '2026-06-30',
    })
    const params = new URLSearchParams(qs)
    expect(params.get('underwriter')).toBe('Acme & Sons')
    expect(params.get('from')).toBe('2026-06-01')
    expect(params.get('to')).toBe('2026-06-30')
    expect(params.has('format')).toBe(false)
  })

  it('includes format when given', () => {
    const qs = _affidavitQueryString({
      underwriter: 'Acme',
      from: '2026-06-01',
      to: '2026-06-30',
      format: 'pdf',
    })
    expect(new URLSearchParams(qs).get('format')).toBe('pdf')
  })
})
