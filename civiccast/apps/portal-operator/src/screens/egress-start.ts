// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Outgoing-feed Start gating shared by ChannelOpsScreen and its tests (beta.5
// walkthrough F-29; hostile review of PR #216, m1 + M3). Kept out of the
// screen module so it only exports components (react-refresh).

import type { EgressStateRow } from '../types/api.generated'

// Mirror civiccast/egress/router.py start_without_config_reason /
// start_disabled_config_reason character for character, so the disabled-button
// reason and the API's 409 detail say the same thing. Pinned by
// tests/policy/test_egress_start_reason_parity.py.
export function startWithoutConfigReason(channelId: string): string {
  return `No outgoing-feed configuration for ${channelId}. Apply a headend preset or the local rehearsal preset first.`
}
export function startDisabledConfigReason(channelId: string): string {
  return `Outgoing feed for ${channelId} is disabled in its egress configuration. Enable it in Outgoing feed configuration, then start.`
}

// Whether the channel's egress configuration row exists and is enabled. The
// router refuses `start` with its own 409 for each of the first two.
export type EgressConfigState = 'missing' | 'disabled' | 'configured'

// How long the screen waits for the daemon to act on a queued Start before it
// tells the operator the start was not applied.
export const START_APPLY_TIMEOUT_MS = 20_000

const START_PENDING_STATES: ReadonlySet<string> = new Set([
  'STARTING',
  'ON_AIR',
  'TRANSITIONING',
  'FALLBACK_SLATE',
  'ERROR',
])

// Snapshot of the daemon state row at the moment a Start was accepted (202).
// The start counts as applied when the row later reports a start-ish state,
// or when either snapshotted value changes. Only server-written values are
// compared with each other -- never a server timestamp against the browser
// clock, which false-alarmed on a station clock >60s behind the workstation
// and on a Start pressed on an already-on-air channel (the daemon no-ops and
// never rewrites updated_at).
export interface StartWatch {
  channelId: string
  issuedAt: number
  // false when the state row had not loaded when the command was accepted;
  // then only a start-ish state counts, so a late first load cannot pass as
  // a change.
  baselineKnown: boolean
  baselineState: string | null
  baselineUpdatedAt: string | null
}

export function startWatchApplied(
  watch: StartWatch | null,
  row: EgressStateRow | null | undefined,
): boolean {
  if (watch == null || row === undefined) return false
  const state = row?.state ?? null
  if (state != null && START_PENDING_STATES.has(state)) return true
  if (!watch.baselineKnown) return false
  return state !== watch.baselineState || (row?.updated_at ?? null) !== watch.baselineUpdatedAt
}
