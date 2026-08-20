// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { formatTimecode, isPlausibleHttpUrl, slugify } from './agendas-format'

describe('formatTimecode', () => {
  it('formats whole hours, minutes, seconds with zero padding', () => {
    expect(formatTimecode(0)).toBe('00:00:00')
    expect(formatTimecode(90)).toBe('00:01:30')
    expect(formatTimecode(3661)).toBe('01:01:01')
    expect(formatTimecode(36000)).toBe('10:00:00')
  })

  it('floors fractional seconds', () => {
    expect(formatTimecode(90.9)).toBe('00:01:30')
  })

  it('returns em-dash for null, undefined, negative, or non-finite values', () => {
    expect(formatTimecode(null)).toBe('—')
    expect(formatTimecode(undefined)).toBe('—')
    expect(formatTimecode(-1)).toBe('—')
    expect(formatTimecode(Number.NaN)).toBe('—')
    expect(formatTimecode(Number.POSITIVE_INFINITY)).toBe('—')
  })
})

describe('slugify', () => {
  it('lowercases and replaces runs of non-slug chars with a single hyphen', () => {
    expect(slugify('Council Meeting 2026/01')).toBe('council-meeting-2026-01')
  })

  it('keeps underscores and hyphens', () => {
    expect(slugify('city_council-2026')).toBe('city_council-2026')
  })

  it('trims leading and trailing hyphens', () => {
    expect(slugify('---hello world---')).toBe('hello-world')
  })

  it('returns the empty string for an empty input', () => {
    expect(slugify('')).toBe('')
    expect(slugify('   ')).toBe('')
  })
})

describe('isPlausibleHttpUrl', () => {
  it('accepts http and https URLs', () => {
    expect(isPlausibleHttpUrl('http://example.com/doc.pdf')).toBe(true)
    expect(isPlausibleHttpUrl('https://example.com/doc.pdf')).toBe(true)
  })

  it('treats empty / null / undefined as acceptable (the field is optional)', () => {
    expect(isPlausibleHttpUrl('')).toBe(true)
    expect(isPlausibleHttpUrl('   ')).toBe(true)
    expect(isPlausibleHttpUrl(null)).toBe(true)
    expect(isPlausibleHttpUrl(undefined)).toBe(true)
  })

  it('rejects schemes that are not http(s) or strings with no scheme', () => {
    expect(isPlausibleHttpUrl('ftp://example.com/x')).toBe(false)
    expect(isPlausibleHttpUrl('example.com/x')).toBe(false)
    expect(isPlausibleHttpUrl('javascript:alert(1)')).toBe(false)
  })
})
