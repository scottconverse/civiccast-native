// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

/**
 * Anchor id for one System Health readiness check's row, so the broadcast
 * readiness card's "Broadcast gate" line can link straight to the blocking
 * item's control (beta.5 walkthrough F-21).
 */
export function healthCheckAnchorId(checkId: string): string {
  return `health-check-${checkId}`
}
