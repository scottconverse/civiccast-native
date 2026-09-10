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
// 'unknown' is a failed configuration-list fetch: the row may be fine, so the
// screen must not tell the operator it is missing (hostile review m7).
export type EgressConfigState = 'missing' | 'disabled' | 'configured' | 'unknown'

export function configCheckFailedReason(channelId: string): string {
  return `Could not check the outgoing-feed configuration for ${channelId}. Retry the check, then start.`
}

// How long the screen waits for the daemon to act on a queued Start before it
// tells the operator the start was not applied.
export const START_APPLY_TIMEOUT_MS = 20_000

// States the daemon only reports by acting on a Start: STARTING is the act
// itself, ON_AIR / TRANSITIONING are the goal. ERROR and FALLBACK_SLATE are
// deliberately NOT here: a row already parked in either before the Start was
// pressed reads identically after the daemon drops the command, so on their
// own they prove nothing (hostile review M4 -- the F-29 silent drop is
// exactly a Start dropped on a channel already sitting in ERROR).
const START_APPLIED_STATES: ReadonlySet<string> = new Set(['STARTING', 'ON_AIR', 'TRANSITIONING'])

// Snapshot of the daemon state row at the moment a Start was accepted (202).
// The start counts as applied when the row later reports a started state,
// or when either snapshotted value changes -- any other state, ERROR and
// FALLBACK_SLATE included, must actually move. Only server-written values are
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
  if (state != null && START_APPLIED_STATES.has(state)) return true
  if (!watch.baselineKnown) return false
  return state !== watch.baselineState || (row?.updated_at ?? null) !== watch.baselineUpdatedAt
}
