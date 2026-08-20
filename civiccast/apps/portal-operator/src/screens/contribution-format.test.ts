import { describe, expect, it } from 'vitest'

import {
  connectionQualityTone,
  contributionRoleLabel,
  guestCanGoOnAir,
  guestStateLabel,
  guestStateTone,
  roomStateLabel,
  roomStateTone,
} from './contribution-format'

describe('contribution-format', () => {
  it('labels room + guest states in plain English', () => {
    // UX-009: a room is "Live" (broadcasting); a guest is "On air" (line below).
    expect(roomStateLabel('live')).toBe('Live')
    expect(roomStateLabel('idle')).toBe('Idle')
    expect(guestStateLabel('connected')).toBe('In waiting room')
    expect(guestStateLabel('on_air')).toBe('On air')
    expect(contributionRoleLabel('public_comment')).toBe('Public comment')
  })

  it('tones reflect status', () => {
    expect(roomStateTone('live')).toBe('ok')
    expect(guestStateTone('on_air')).toBe('ok')
    expect(guestStateTone('muted')).toBe('warn')
    expect(connectionQualityTone('poor')).toBe('warn')
    expect(connectionQualityTone('good')).toBe('ok')
  })

  it('gates on-air on admission (the waiting-room rule, not just a 409)', () => {
    expect(guestCanGoOnAir('connected', null)).toBe(false) // held in the waiting room
    expect(guestCanGoOnAir('connected', '2026-01-01T00:00:00Z')).toBe(true)
    expect(guestCanGoOnAir('dropped', '2026-01-01T00:00:00Z')).toBe(false) // terminal
  })
})
