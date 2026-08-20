import { describe, expect, it } from 'vitest'

import {
  formatDays,
  hhmmToMinute,
  minuteToHHMM,
  pickStrategyLabel,
  slotActionLabel,
  slotActionTone,
} from './autoschedule-format'

describe('pickStrategyLabel', () => {
  it('labels the known strategies', () => {
    expect(pickStrategyLabel('top_result')).toBe('First match')
    expect(pickStrategyLabel('random_result')).toBe('Random')
    expect(pickStrategyLabel('newest')).toBe('Newest first')
  })

  it('falls back gracefully', () => {
    expect(pickStrategyLabel(undefined)).toBe('Newest first')
    expect(pickStrategyLabel('weird')).toBe('weird')
  })
})

describe('slotActionLabel / slotActionTone', () => {
  it('labels every slot action', () => {
    expect(slotActionLabel('fill')).toBe('Will air')
    expect(slotActionLabel('occupied')).toBe('Already scheduled')
    expect(slotActionLabel('no_asset')).toBe('No eligible video')
    expect(slotActionLabel('unplayable')).toBe('No usable duration')
  })

  it('tones each action', () => {
    expect(slotActionTone('fill')).toBe('ok')
    expect(slotActionTone('occupied')).toBe('muted')
    expect(slotActionTone('no_asset')).toBe('warn')
    expect(slotActionTone('unplayable')).toBe('warn')
  })
})

describe('minuteToHHMM / hhmmToMinute', () => {
  it('formats minutes-of-day as wall clock', () => {
    expect(minuteToHHMM(0)).toBe('00:00')
    expect(minuteToHHMM(90)).toBe('01:30')
    expect(minuteToHHMM(18 * 60)).toBe('18:00')
    expect(minuteToHHMM(22 * 60)).toBe('22:00')
    expect(minuteToHHMM(24 * 60)).toBe('24:00')
  })

  it('parses wall clock back to minutes', () => {
    expect(hhmmToMinute('00:00')).toBe(0)
    expect(hhmmToMinute('01:30')).toBe(90)
    expect(hhmmToMinute('18:00')).toBe(1080)
    expect(hhmmToMinute('24:00')).toBe(1440)
  })

  it('round-trips', () => {
    for (const minute of [0, 90, 1080, 1320, 1440]) {
      expect(hhmmToMinute(minuteToHHMM(minute))).toBe(minute)
    }
  })
})

describe('formatDays', () => {
  it('renders sorted weekday labels', () => {
    expect(formatDays([0, 2, 4])).toBe('Mon, Wed, Fri')
    expect(formatDays([4, 0, 2])).toBe('Mon, Wed, Fri')
    expect(formatDays([6])).toBe('Sun')
  })

  it('handles the empty case', () => {
    expect(formatDays([])).toBe('No days')
  })
})
