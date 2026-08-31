// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Renders the derived asset lifecycle status (see assetStatus.ts) with the
// same pill visuals as ReadinessBadge/StateBadge so all three badge
// families read as one system. The detail sentence is a native title
// tooltip for mouse users AND always-present sr-only text (a hover-only
// tooltip is inaccessible to keyboard/touch/screen-reader use).

import type { AssetStatus } from './assetStatus'

const TONE_STYLES: Record<AssetStatus['tone'], { bg: string; fg: string }> = {
  ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
  info: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
  neutral: { bg: 'var(--cc-surface-2)', fg: 'var(--cc-ink-2)' },
}

export function AssetStatusBadge({
  status,
  inFlightJobsCount,
}: {
  status: AssetStatus
  /** Count of pending/running transcode jobs, when known. */
  inFlightJobsCount?: number
}) {
  const tone = TONE_STYLES[status.tone]
  const suffix =
    (status.id === 'transcoding' || status.id === 'queued_transcode') &&
    inFlightJobsCount != null &&
    inFlightJobsCount > 0
      ? ` (${inFlightJobsCount})`
      : ''
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: tone.bg, color: tone.fg }}
      title={status.detail}
    >
      <span aria-hidden="true">{status.dot}</span>
      {status.label}
      {suffix}
      <span className="sr-only">{` — ${status.detail}`}</span>
    </span>
  )
}
