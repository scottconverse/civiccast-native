// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Plain-English labels + tones for the S17 Remote Contribution console. Split
// out so the screen file stays react-refresh-clean (components-only export).
// The generated API types mark enum fields optional (string | undefined), so
// every helper tolerates undefined and falls back gracefully.

import type { StaffIdentityResponse } from '../types/api.generated'

export type Tone = 'neutral' | 'ok' | 'warn' | 'info'

export function roomStateLabel(state: string | undefined): string {
  const map: Record<string, string> = {
    idle: 'Idle',
    open: 'Open',
    // Room state is "Live" (the room/channel is broadcasting), distinct from a
    // GUEST being "On air" (guestStateLabel) — UX-009 disambiguation.
    live: 'Live',
    closing: 'Closing',
    closed: 'Closed',
  }
  return state ? (map[state] ?? state) : ''
}

export function roomStateTone(state: string | undefined): Tone {
  if (state === 'live') return 'ok'
  if (state === 'open') return 'info'
  return 'neutral'
}

export function contributionRoleLabel(role: string | undefined): string {
  const map: Record<string, string> = {
    council_member: 'Council member',
    presenter: 'Presenter',
    public_comment: 'Public comment',
  }
  return role ? (map[role] ?? role) : ''
}

export function guestStateLabel(state: string | undefined): string {
  const map: Record<string, string> = {
    invited: 'Invited',
    joining: 'Joining',
    connected: 'In waiting room',
    on_air: 'On air',
    muted: 'Muted',
    dropped: 'Dropped',
    ended: 'Ended',
  }
  return state ? (map[state] ?? state) : ''
}

export function guestStateTone(state: string | undefined): Tone {
  if (state === 'on_air') return 'ok'
  if (state === 'muted') return 'warn'
  if (state === 'connected' || state === 'joining') return 'info'
  return 'neutral'
}

export function connectionQualityLabel(quality: string | undefined): string {
  const map: Record<string, string> = {
    unknown: 'Unknown',
    good: 'Good',
    degraded: 'Degraded',
    poor: 'Poor',
  }
  return quality ? (map[quality] ?? quality) : 'Unknown'
}

export function connectionQualityTone(quality: string | undefined): Tone {
  if (quality === 'good') return 'ok'
  if (quality === 'degraded' || quality === 'poor') return 'warn'
  return 'neutral'
}

/** Whether a guest can be put on-air: must be admitted (out of the waiting
 *  room) and not in a terminal state. Mirrors the server's GuestNotAdmittedError
 *  gate so the button is disabled, not just 409-on-click. */
export function guestCanGoOnAir(
  state: string | undefined,
  admittedAt: string | null | undefined,
): boolean {
  return admittedAt != null && state !== 'dropped' && state !== 'ended'
}

/** Whether the identity holds any of `roles`, gating on the DERIVED product
 *  roles the backend populates via roles_for_identity() — NOT raw token scopes
 *  (scopes are "operator"/"admin" and never contain product-role names, which
 *  left the S17 console dead for real tokens; QA-001). Lives here so the screen
 *  file stays react-refresh-clean (components-only export). */
export function hasRole(
  identity: StaffIdentityResponse | undefined,
  roles: string[],
): boolean {
  const granted: string[] = identity?.roles ?? []
  return roles.some((r) => granted.includes(r))
}
