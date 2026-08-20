import { describe, expect, it } from 'vitest'

import { elapsedSinceLabel } from './takeover-format'

const T0 = Date.parse('2026-06-20T18:00:00Z')

describe('elapsedSinceLabel', () => {
  it('reads just now under a minute', () => {
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 + 20_000)).toBe('just now')
  })

  it('reads minutes', () => {
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 + 60_000)).toBe('1 min')
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 + 5 * 60_000)).toBe('5 min')
  })

  it('reads hours and minutes', () => {
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 + 60 * 60_000)).toBe('1 hr')
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 + 95 * 60_000)).toBe('1 hr 35 min')
  })

  it('never goes negative', () => {
    expect(elapsedSinceLabel('2026-06-20T18:00:00Z', T0 - 60_000)).toBe('just now')
  })
})
