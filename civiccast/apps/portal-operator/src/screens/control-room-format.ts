// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Plain-English labels for the S16 Production Control Room console. Split out
// so the screen file stays react-refresh-clean (components-only export).

export function deviceKindLabel(kind: string): string {
  const map: Record<string, string> = {
    obs: 'OBS Studio',
    vmix: 'vMix',
    atem: 'Blackmagic ATEM',
    hyperdeck: 'HyperDeck',
    ptz: 'PTZ camera',
    osc: 'OSC',
    tcp: 'TCP device',
    http: 'HTTP device',
    casparcg: 'CasparCG',
    gpi: 'GPI',
    serial: 'Serial (RS-232/422)',
  }
  return map[kind] ?? kind
}

export function cueActionLabel(action: string): string {
  const map: Record<string, string> = {
    scene: 'Take scene',
    input: 'Take input',
    transition: 'Transition',
    macro: 'Run macro',
    deck_play: 'Play deck',
    deck_cue: 'Cue deck',
    ptz_preset: 'Recall PTZ preset',
    osc: 'Send OSC',
    http: 'Send HTTP',
    overlay_push: 'Push overlay',
    overlay_clear: 'Clear overlay',
    gpi_pulse: 'GPI pulse',
    serial_send: 'Serial send',
    router_take: 'Router take',
  }
  return map[action] ?? action
}

export type ReachTone = 'ok' | 'warn' | 'neutral'

export function deviceReachability(
  enabled: boolean,
  reachable: boolean | null,
): { label: string; tone: ReachTone } {
  if (!enabled) return { label: 'Disabled', tone: 'neutral' }
  if (reachable === true) return { label: 'Reachable', tone: 'ok' }
  if (reachable === false) return { label: 'Unreachable', tone: 'warn' }
  return { label: 'Not probed', tone: 'neutral' }
}

export function sessionStateLabel(state: string): string {
  return state === 'open' ? 'Live session open' : 'Session closed'
}

// Mirrors civiccast.control_room.models.DEVICE_HEALTH_STALE_AFTER_SECONDS.
export const DEVICE_HEALTH_STALE_AFTER_MS = 300_000

export function deviceHealthLabel(
  lastReachable: boolean | null | undefined,
  lastProbedAt: string | null | undefined,
  now: Date = new Date(),
): { label: string; tone: ReachTone } {
  if (!lastProbedAt || lastReachable == null) {
    return { label: 'Never probed', tone: 'neutral' }
  }
  const age = now.getTime() - new Date(lastProbedAt).getTime()
  if (age > DEVICE_HEALTH_STALE_AFTER_MS) {
    return { label: 'Stale — probe again', tone: 'warn' }
  }
  return lastReachable ? { label: 'Healthy', tone: 'ok' } : { label: 'Unreachable', tone: 'warn' }
}

export function cueResultLabel(result: string): string {
  const map: Record<string, string> = { planned: 'Planned', fired: 'Fired', failed: 'Failed' }
  return map[result] ?? result
}
