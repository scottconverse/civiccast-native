import type { AssetState } from '../types/asset'
import { STATE_META } from '../types/asset'

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

export function StateBadge({ state }: { state: AssetState }) {
  const meta = STATE_META[state]
  const tone = TONE_STYLES[meta.tone]

  return (
    <span
      title={meta.description}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: tone.bg, color: tone.fg }}
    >
      <span
        aria-hidden="true"
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: tone.fg }}
      />
      {meta.label}
    </span>
  )
}
