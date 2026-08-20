import { describe, expect, it } from 'vitest'

import { humanizeDuration } from './format'

describe('humanizeDuration', () => {
  it('shows seconds under a minute', () => {
    expect(humanizeDuration(30)).toBe('30s')
    expect(humanizeDuration(59)).toBe('59s')
  })

  it('shows whole minutes under an hour', () => {
    expect(humanizeDuration(60)).toBe('1m')
    expect(humanizeDuration(2700)).toBe('45m')
  })

  it('shows hours and minutes at or over an hour', () => {
    expect(humanizeDuration(3600)).toBe('1h 0m')
    expect(humanizeDuration(5400)).toBe('1h 30m')
    expect(humanizeDuration(7320)).toBe('2h 2m')
  })

  it('floors fractional seconds and guards non-positive / invalid input', () => {
    expect(humanizeDuration(30.9)).toBe('30s')
    expect(humanizeDuration(0)).toBe('0s')
    expect(humanizeDuration(-5)).toBe('0s')
    expect(humanizeDuration(Number.NaN)).toBe('0s')
  })
})
