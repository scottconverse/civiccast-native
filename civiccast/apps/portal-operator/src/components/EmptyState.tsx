// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * The one designed empty state for operator-console screens.
 *
 * Field survey 2026-08-30: about a dozen console pages rendered their
 * success-empty state as a bare grey one-liner ("No devices yet."), which a
 * non-technical viewer reads as "nothing there / broken". Missing Media and
 * Assets had already designed the state (dashed panel, headline + explainer);
 * this component generalizes that pattern so every page speaks the same way:
 *
 * - `headline`: short, factual, no apology ("No recordings yet.")
 * - `body`: one sentence on what the screen does for a station in plain
 *   language, plus one sentence on how it gets populated.
 * - `action` (optional): the page's primary next step — keep any existing
 *   disabled-until-valid logic in the element passed in.
 */
import type { ReactNode } from 'react'

export function EmptyState({
  headline,
  body,
  action,
}: {
  headline: string
  body: ReactNode
  action?: ReactNode
}) {
  return (
    <div
      className="my-4 flex flex-col items-center gap-3 rounded-md p-8 text-center"
      style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)' }}
    >
      <div className="text-sm font-semibold">{headline}</div>
      <div className="max-w-xl text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {body}
      </div>
      {action != null && <div>{action}</div>}
    </div>
  )
}
