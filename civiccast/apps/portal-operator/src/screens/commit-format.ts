import type { ChannelLogEntry, CommitToAirPlan, CommitToAirReport } from '../types/api.generated'

// Non-component helpers for the Commit-to-Air panel live here (mirrors
// alerts-format.ts) so the screen file only exports components and React Fast
// Refresh stays happy.

export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'muted'

// The generated dispatch_status is an optional inline union; name it here.
export type CommitDispatchStatus = NonNullable<CommitToAirReport['dispatch_status']>

/** Plain-English label for a committed report's dispatch state. */
export function reportStatusLabel(status: CommitDispatchStatus): string {
  switch (status) {
    case 'pending':
      return 'Preparing'
    case 'queued':
      return 'Queued to air'
    case 'acknowledged':
      return 'On air (confirmed)'
    case 'error':
      return "Couldn't reach the engine"
    case 'cancelled':
      return 'Rolled back'
  }
}

export function reportTone(status: CommitDispatchStatus): Tone {
  switch (status) {
    case 'acknowledged':
    case 'queued':
      return 'ok'
    case 'error':
      return 'err'
    case 'cancelled':
      return 'muted'
    case 'pending':
      return 'info'
  }
}

const _OCCURRENCE_SKIP_LABEL: Record<string, string> = {
  skipped_conflict: 'Skipped (conflict)',
  skipped_asset: 'Skipped (media)',
  cancelled: 'Cancelled',
}

/** Status badge for one upcoming occurrence in the commit list. */
export function occurrenceBadge(
  entry: ChannelLogEntry,
  committedOccurrenceIds: ReadonlySet<string>,
): { label: string; tone: Tone } {
  if (!entry.schedule_item_id) {
    return { label: 'Not ready to air', tone: 'muted' }
  }
  if (committedOccurrenceIds.has(entry.occurrence_id)) {
    return { label: 'Committed', tone: 'ok' }
  }
  // 'scheduled' = a materialized slot occurrence; 'manual' = a directly
  // scheduled item (F-RC4-2). Both are committable, not skips — everything
  // else (skipped_conflict/skipped_asset/cancelled) is a warn state.
  if (entry.status !== 'scheduled' && entry.status !== 'manual') {
    return { label: _OCCURRENCE_SKIP_LABEL[entry.status] ?? entry.status, tone: 'warn' }
  }
  return { label: 'Ready to review', tone: 'info' }
}

/** A program can be aired only when the dry-run passed AND the operator may manage air. */
export function canApprove(plan: CommitToAirPlan | undefined, canManage: boolean): boolean {
  return Boolean(plan?.dry_run_passed) && canManage
}

/** Occurrences with a live (not rolled-back / not-errored) commit are "on air". */
export function committedOccurrenceIds(reports: CommitToAirReport[]): Set<string> {
  return new Set(
    reports
      .filter(
        (r) =>
          r.dispatch_status === 'pending' ||
          r.dispatch_status === 'queued' ||
          r.dispatch_status === 'acknowledged',
      )
      .map((r) => r.occurrence_id),
  )
}
