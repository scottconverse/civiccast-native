import type { SourcedClaim } from '../../types/api.generated'

function fmtRange(startSeconds: number, endSeconds: number): string {
  const fmt = (value: number) => {
    const whole = Math.floor(value)
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
  }
  return `${fmt(startSeconds)}-${fmt(endSeconds)}`
}

export function SourcedClaimList({
  claims,
  onSeek,
}: {
  claims: SourcedClaim[]
  onSeek: (cueId: string) => void
}) {
  if (claims.length === 0) {
    return (
      <div
        className="rounded-md p-3 text-xs"
        style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
      >
        This summary has no sourced claims. Next step: regenerate the summary from committed
        transcript cues before approval.
      </div>
    )
  }
  return (
    <section aria-label="Sourced claims" className="grid gap-2">
      {claims.map((claim) => (
        <article
          key={claim.claim_id}
          className="rounded-md p-3"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          <div className="text-sm font-semibold">{claim.text}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {(claim.transcript_ranges ?? []).map((range) => (
              <button
                key={`${claim.claim_id}-${range.cue_id}-${range.start_seconds}`}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  const active = document.activeElement
                  onSeek(range.cue_id)
                  if (active instanceof HTMLElement) {
                    window.requestAnimationFrame(() => active.focus())
                  }
                }}
                className="rounded-md px-2 py-1 text-xs font-semibold"
                style={{
                  background: 'var(--cc-surface)',
                  border: '1px solid var(--cc-line-strong)',
                  color: 'var(--cc-brand-2)',
                }}
              >
                {range.cue_id} {fmtRange(range.start_seconds, range.end_seconds)}
              </button>
            ))}
          </div>
        </article>
      ))}
    </section>
  )
}
