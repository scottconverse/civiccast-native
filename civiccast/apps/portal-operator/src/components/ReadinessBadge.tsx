// S7 media lifecycle: the operator-facing "ready for air" badge.
// Spec §5 Media Library Dashboard: 🟢 Ready | 🟡 Transcoding (45%) | 🔴
// Missing | ⚪ Rejected. Colors reuse the same design tokens StateBadge
// uses so the two badge families read as one system.

export type ReadinessState =
  | 'not_ready'
  | 'pending_transcode'
  | 'transcoding'
  | 'ready'
  | 'missing_file'
  | 'rejected'

const READINESS_META: Record<
  ReadinessState,
  { label: string; tone: 'ok' | 'warn' | 'err' | 'info' | 'neutral'; dot: string }
> = {
  ready: { label: 'Ready', tone: 'ok', dot: '🟢' },
  transcoding: { label: 'Transcoding', tone: 'warn', dot: '🟡' },
  pending_transcode: { label: 'Queued for transcode', tone: 'warn', dot: '🟡' },
  missing_file: { label: 'Missing', tone: 'err', dot: '🔴' },
  rejected: { label: 'Rejected', tone: 'err', dot: '🔴' },
  not_ready: { label: 'Not ready', tone: 'neutral', dot: '⚪' },
}

const TONE_STYLES: Record<
  'ok' | 'warn' | 'err' | 'info' | 'neutral',
  { bg: string; fg: string }
> = {
  ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)' },
  err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)' },
  info: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-info)' },
  neutral: { bg: 'var(--cc-surface-2)', fg: 'var(--cc-ink-2)' },
}

export function ReadinessBadge({
  state,
  inFlightJobsCount,
  progressPercent,
}: {
  state: ReadinessState
  /** Count of pending/running transcode jobs, when known (dashboard row). */
  inFlightJobsCount?: number
  /** Progress of the furthest-along in-flight job, when known (detail view). */
  progressPercent?: number
}) {
  const meta = READINESS_META[state] ?? READINESS_META.not_ready
  const tone = TONE_STYLES[meta.tone]
  const suffix =
    state === 'transcoding' && progressPercent != null
      ? ` (${progressPercent}%)`
      : (state === 'transcoding' || state === 'pending_transcode') &&
          inFlightJobsCount != null &&
          inFlightJobsCount > 0
        ? ` (${inFlightJobsCount})`
        : ''

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: tone.bg, color: tone.fg }}
    >
      <span aria-hidden="true">{meta.dot}</span>
      {meta.label}
      {suffix}
    </span>
  )
}
