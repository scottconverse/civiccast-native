import { useQuery } from '@tanstack/react-query'
import { ApiError, getEgressHealth, getLoudnessPlan } from '../api/client'
import type { ChannelLoudnessPlan } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function fmtLufs(value: number): string {
  return `${value.toFixed(1)} LUFS`
}

// Presentational only (no data fetching) so it unit-tests without a network.
export function LoudnessPlanView({
  plan,
  latestLoudnessLufs,
  loading,
  error,
}: {
  plan: ChannelLoudnessPlan | undefined
  latestLoudnessLufs?: number | null
  loading?: boolean
  error?: unknown
}) {
  return (
    <section
      aria-label="Loudness"
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Loudness</h2>
        {latestLoudnessLufs != null && (
          <span
            className="cc-mono rounded-full px-2 py-0.5 text-[11px]"
            style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
          >
            Measured {fmtLufs(latestLoudnessLufs)}
          </span>
        )}
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        Each output is normalised to its destination&rsquo;s loudness standard — cable to
        ATSC&nbsp;A/85 (&minus;24&nbsp;LKFS), streaming to &minus;16&nbsp;LUFS.
      </p>
      {loading && (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          Loading the loudness plan…
        </p>
      )}
      {Boolean(error) && (
        <div
          role="alert"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
        >
          {apiMessage(error, 'The loudness plan could not load.')}
        </div>
      )}
      {plan && plan.sinks.length === 0 && (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          No egress outputs are configured for this channel yet.
        </p>
      )}
      {plan && plan.sinks.length > 0 && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs uppercase" style={{ color: 'var(--cc-ink-3)' }}>
              <th scope="col" className="py-1 pr-3 font-medium">
                Output
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Regime
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Target
              </th>
              <th scope="col" className="py-1 font-medium">
                Standard
              </th>
            </tr>
          </thead>
          <tbody>
            {plan.sinks.map((sink) => (
              <tr key={sink.label} style={{ borderTop: '1px solid var(--cc-line)' }}>
                <td className="py-1.5 pr-3 font-medium" style={{ color: 'var(--cc-ink)' }}>
                  {sink.label}
                  <span className="ml-1 cc-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                    {sink.kind}
                  </span>
                </td>
                <td className="py-1.5 pr-3">
                  <span
                    className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
                  >
                    {sink.short_label}
                  </span>
                  {sink.requires_reencode && (
                    <span className="ml-1 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                      re-normalised
                    </span>
                  )}
                </td>
                <td className="cc-mono py-1.5 pr-3" style={{ color: 'var(--cc-ink)' }}>
                  {fmtLufs(sink.effective_target_lufs)}
                </td>
                <td className="py-1.5 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  {sink.standard_label}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function LoudnessPlanCard({ channelId, enabled = true }: { channelId: string; enabled?: boolean }) {
  const planQuery = useQuery({
    queryKey: ['loudness-plan', channelId],
    queryFn: () => getLoudnessPlan(channelId),
    enabled,
    retry: false,
  })
  const healthQuery = useQuery({
    queryKey: ['egress-health', channelId],
    queryFn: () => getEgressHealth(channelId),
    retry: false,
  })
  // Pick the most recent sample that actually carries a measurement, regardless
  // of the endpoint's ordering, so the chip never shows a stale or null reading.
  const measured =
    (healthQuery.data ?? [])
      .filter((sample) => sample.last_loudness_lufs != null)
      .sort(
        (a, b) => new Date(b.sampled_at).getTime() - new Date(a.sampled_at).getTime(),
      )[0]?.last_loudness_lufs ?? null
  return (
    <LoudnessPlanView
      plan={
        enabled
          ? planQuery.data
          : {
              channel_id: channelId,
              baseline_target_lufs: -16,
              baseline_tolerance_lufs: 2,
              sinks: [],
            }
      }
      latestLoudnessLufs={measured}
      loading={enabled && planQuery.isLoading}
      error={enabled ? planQuery.error : undefined}
    />
  )
}
