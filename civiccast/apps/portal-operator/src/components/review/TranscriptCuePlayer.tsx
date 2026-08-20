import type { TranscriptRange } from '../../types/api.generated'

function fmtTime(seconds: number): string {
  const whole = Math.floor(seconds)
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TranscriptCuePlayer({
  ranges,
  activeCueId,
}: {
  ranges: TranscriptRange[]
  activeCueId: string | null
}) {
  const active = ranges.find((range) => range.cue_id === activeCueId) ?? ranges[0]
  return (
    <section
      aria-label="Inline transcript player"
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Transcript seek target
        </div>
        <div className="mt-1 text-sm font-semibold">
          {active ? `${active.cue_id} / ${fmtTime(active.start_seconds)}-${fmtTime(active.end_seconds)}` : 'No cue selected'}
        </div>
      </div>
      <div className="grid gap-2" role="list" aria-label="Transcript cue ranges">
        {ranges.map((range) => {
          const selected = range.cue_id === active?.cue_id
          return (
            <div
              key={`${range.cue_id}-${range.start_seconds}`}
              role="listitem"
              aria-current={selected ? 'true' : undefined}
              className="rounded-md px-3 py-2 text-xs"
              style={{
                background: selected ? 'var(--cc-brand-soft)' : 'var(--cc-surface-2)',
                border: selected ? '1px solid var(--cc-brand)' : '1px solid var(--cc-line)',
                color: selected ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
              }}
            >
              {range.cue_id}: {fmtTime(range.start_seconds)}-{fmtTime(range.end_seconds)}
            </div>
          )
        })}
      </div>
    </section>
  )
}
