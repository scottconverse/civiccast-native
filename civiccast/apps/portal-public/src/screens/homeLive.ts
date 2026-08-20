// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Live re-resolve helpers for HomeScreen, kept in a non-component module so the
// screen file only exports its component (react-refresh/only-export-components).
import type { PublicLiveStatus } from '../types'

// Re-resolve the live stream this often. Must stay inside the surge switch's
// load-monitor window (6s) so the origin's concurrent-viewer count reflects the
// real audience — this poll IS that load signal (see the /current backend), and
// a stale count would make the switch's release decision unsafe.
export const LIVE_POLL_SECONDS = 4

export function sameLiveStatus(a: PublicLiveStatus | null, b: PublicLiveStatus): boolean {
  return (
    a !== null &&
    a.state === b.state &&
    a.manifest_url === b.manifest_url &&
    a.live_session_id === b.live_session_id &&
    a.title === b.title
  )
}
