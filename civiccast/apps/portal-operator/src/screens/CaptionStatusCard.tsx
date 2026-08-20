import { useQuery } from '@tanstack/react-query'
import { ApiError, getCaptionProofs, getCaptionStatus } from '../api/client'
import type { CaptionStatusResponse, EgressCaptionProofSample } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

// Presentational only (no data fetching) so it unit-tests without a network.
export function CaptionStatusView({
  status,
  proofs,
  loading,
  error,
}: {
  status: CaptionStatusResponse | undefined
  proofs: EgressCaptionProofSample[] | undefined
  loading?: boolean
  error?: unknown
}) {
  const on = status?.caption_status === 'on'
  return (
    <section
      aria-label="Captions"
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Captions</h2>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
          style={{ background: on ? 'var(--cc-ok-soft)' : 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
        >
          {loading ? 'Checking…' : on ? 'Captions on' : 'Not verified'}
        </span>
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        Captions show as <strong>on</strong> only after CivicCast decodes them back from the
        emitted stream and they match. This proves carriage at the egress boundary; it is not a
        claim of FCC Part&nbsp;79 compliance.
      </p>
      {Boolean(error) && (
        <div
          role="alert"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
        >
          {apiMessage(error, 'Caption status could not load.')}
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Decode-back proofs
        </summary>
        {proofs && proofs.length === 0 && (
          <p className="m-0 mt-2 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
            No caption decode-back proofs yet for this channel.
          </p>
        )}
        {proofs && proofs.length > 0 && (
          <table className="mt-2 w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs uppercase" style={{ color: 'var(--cc-ink-3)' }}>
                <th scope="col" className="py-1 pr-3 font-medium">
                  When
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Result
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  Matched
                </th>
                <th scope="col" className="py-1 font-medium">
                  Detail
                </th>
              </tr>
            </thead>
            <tbody>
              {proofs.map((proof, index) => (
                <tr
                  key={`${proof.sampled_at}-${index}`}
                  style={{ borderTop: '1px solid var(--cc-line)' }}
                >
                  <td className="py-1.5 pr-3 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                    {fmtTime(proof.sampled_at)}
                  </td>
                  <td className="py-1.5 pr-3">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                      style={{
                        background:
                          proof.status === 'PASS' ? 'var(--cc-ok-soft)' : 'var(--cc-warn-soft)',
                        color: 'var(--cc-ink)',
                      }}
                    >
                      {proof.status}
                    </span>
                  </td>
                  <td className="cc-mono py-1.5 pr-3" style={{ color: 'var(--cc-ink)' }}>
                    {proof.matched_cue_count}/{proof.expected_cue_count}
                  </td>
                  <td className="py-1.5 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    {proof.blocker ?? 'matched within tolerance'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
    </section>
  )
}

export function CaptionStatusCard({ channelId }: { channelId: string }) {
  const statusQuery = useQuery({
    queryKey: ['caption-status', channelId],
    queryFn: () => getCaptionStatus(channelId),
    retry: false,
  })
  const proofsQuery = useQuery({
    queryKey: ['caption-proofs', channelId],
    queryFn: () => getCaptionProofs(channelId, 10),
    retry: false,
  })
  return (
    <CaptionStatusView
      status={statusQuery.data}
      proofs={proofsQuery.data}
      loading={statusQuery.isLoading}
      error={statusQuery.error}
    />
  )
}
