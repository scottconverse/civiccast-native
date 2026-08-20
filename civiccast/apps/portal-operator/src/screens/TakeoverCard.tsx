import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  beginTakeover,
  getTakeoverState,
  handbackTakeover,
  listTakeoverAudit,
} from '../api/client'
import type { TakeoverSession } from '../types/api.generated'
import { elapsedSinceLabel, formatWhen } from './takeover-format'

const POLL_MS = 15_000

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

const CARD_STYLE = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }
const SUBCARD_STYLE = { background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }

function fieldStyle() {
  return {
    background: 'var(--cc-surface)',
    border: '1px solid var(--cc-line)',
    color: 'var(--cc-ink)',
  }
}

/** Wall-clock that ticks for the elapsed label. Date.now() is read only in an
 * effect (never during render) so the render stays pure. */
function useNow(intervalMs: number): number {
  // Lazy init (impure read allowed in an initializer) + interval-only effect —
  // matches the Clock pattern in shell/TopBar.tsx and keeps render pure.
  const [now, setNow] = useState<number>(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function LiveBadge({ session, now }: { session: TakeoverSession; now: number }) {
  const who = session.operator_name ?? session.operator_id
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-wrap items-center gap-2 rounded-md p-2 text-sm"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
    >
      <span aria-hidden="true">🔴</span>
      <span className="font-semibold">
        Live takeover — {who}, {elapsedSinceLabel(session.took_over_at, now)}
      </span>
    </div>
  )
}

function AuditPanel({ sessions }: { sessions: TakeoverSession[] }) {
  if (sessions.length === 0) {
    return (
      <div className="text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        No live takeovers have been recorded for this channel.
      </div>
    )
  }
  return (
    <div className="grid gap-2">
      {sessions.map((s) => (
        <div key={s.session_id} className="rounded-md p-2 text-xs" style={SUBCARD_STYLE}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{s.source_label}</span>
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
              style={
                s.returned_at
                  ? { background: 'var(--cc-surface-3)', color: 'var(--cc-ink-3)' }
                  : { background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }
              }
            >
              {s.returned_at ? 'Returned' : 'Live'}
            </span>
          </div>
          <div className="cc-mono mt-0.5" style={{ color: 'var(--cc-ink-3)' }}>
            {s.operator_name ?? s.operator_id} · took live {formatWhen(s.took_over_at)}
            {s.returned_at ? ` · returned ${formatWhen(s.returned_at)}` : ''}
          </div>
          {s.reason && <div className="mt-0.5" style={{ color: 'var(--cc-ink-2)' }}>Reason: {s.reason}</div>}
        </div>
      ))}
    </div>
  )
}

export function TakeoverCard({
  channelId,
  canManage,
  canViewAudit,
}: {
  channelId: string | undefined
  canManage: boolean
  canViewAudit: boolean
}) {
  const queryClient = useQueryClient()
  const [arming, setArming] = useState<'take' | 'return' | null>(null)
  const [text, setText] = useState('')
  const now = useNow(30_000)

  const stateQuery = useQuery({
    queryKey: ['takeover-state', channelId],
    queryFn: () => getTakeoverState(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const auditQuery = useQuery({
    queryKey: ['takeover-audit', channelId],
    queryFn: () => listTakeoverAudit(channelId ?? ''),
    enabled: Boolean(channelId) && canViewAudit,
    refetchInterval: POLL_MS,
  })

  function reset() {
    setArming(null)
    setText('')
  }
  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['takeover-state', channelId] })
    void queryClient.invalidateQueries({ queryKey: ['takeover-audit', channelId] })
    reset()
  }

  const beginMutation = useMutation({
    mutationFn: (reason: string) =>
      beginTakeover(channelId ?? '', { reason: reason || null }),
    onSuccess: invalidate,
  })
  const handbackMutation = useMutation({
    mutationFn: (notes: string) =>
      handbackTakeover(channelId ?? '', { notes: notes || null }),
    onSuccess: invalidate,
  })

  const state = stateQuery.data
  const active = state?.active_session ?? null
  const busy = beginMutation.isPending || handbackMutation.isPending
  const mutationError = beginMutation.error ?? handbackMutation.error

  return (
    <section className="rounded-md p-4" style={CARD_STYLE} aria-label="Live takeover">
      <h2 className="m-0 text-lg font-semibold">Live takeover</h2>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        {channelId
          ? 'Put a live source on this channel now, overriding the schedule, then return when done.'
          : 'Select a channel to manage live takeover.'}
      </div>

      {stateQuery.isError && (
        <div role="alert" className="mt-3 text-sm" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(stateQuery.error, 'Could not load the takeover state.')}
        </div>
      )}

      {state && (
        <div className="mt-3 grid gap-3">
          {active ? (
            <>
              <LiveBadge session={active} now={now} />
              {canManage &&
                (arming === 'return' ? (
                  <div className="grid gap-2 rounded-md p-3" style={SUBCARD_STYLE}>
                    <label className="text-xs font-semibold" htmlFor="takeover-notes">
                      Notes (optional)
                    </label>
                    <input
                      id="takeover-notes"
                      type="text"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder="e.g. meeting adjourned"
                      className="rounded-md px-3 py-2 text-sm outline-none"
                      style={fieldStyle()}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => handbackMutation.mutate(text)}
                        className="rounded-md px-3 py-2 text-sm font-semibold"
                        style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
                      >
                        {busy ? 'Returning…' : 'Confirm return to schedule'}
                      </button>
                      <button
                        type="button"
                        onClick={reset}
                        className="rounded-md px-3 py-2 text-sm font-medium"
                        style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
                      >
                        Stay live
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <button
                      type="button"
                      onClick={() => setArming('return')}
                      className="rounded-md px-3 py-2 text-sm font-semibold"
                      style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
                    >
                      Return to schedule
                    </button>
                  </div>
                ))}
            </>
          ) : (
            <>
              <div className="text-sm" style={{ color: 'var(--cc-ink-2)' }}>
                This channel is on its scheduled program.
              </div>
              {canManage &&
                (arming === 'take' ? (
                  <div className="grid gap-2 rounded-md p-3" style={SUBCARD_STYLE}>
                    <label className="text-xs font-semibold" htmlFor="takeover-reason">
                      Why are you going live? (optional)
                    </label>
                    <input
                      id="takeover-reason"
                      type="text"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder="e.g. emergency council session"
                      className="rounded-md px-3 py-2 text-sm outline-none"
                      style={fieldStyle()}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => beginMutation.mutate(text)}
                        className="rounded-md px-3 py-2 text-sm font-semibold"
                        style={{ background: 'var(--cc-err)', color: 'white' }}
                      >
                        {busy ? 'Going live…' : 'Confirm take live'}
                      </button>
                      <button
                        type="button"
                        onClick={reset}
                        className="rounded-md px-3 py-2 text-sm font-medium"
                        style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <button
                      type="button"
                      disabled={!state.can_takeover}
                      onClick={() => setArming('take')}
                      className="rounded-md px-3 py-2 text-sm font-semibold"
                      style={{
                        background: state.can_takeover ? 'var(--cc-err)' : 'var(--cc-surface-3)',
                        color: state.can_takeover ? 'white' : 'var(--cc-ink-3)',
                      }}
                    >
                      Take live
                    </button>
                    {!state.can_takeover && (
                      <span className="ml-2 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                        No live source is ready yet.
                      </span>
                    )}
                  </div>
                ))}
            </>
          )}

          {!canManage && (
            <div className="text-sm" style={{ color: 'var(--cc-ink-3)' }}>
              Taking a channel live requires the meeting operator or setup admin role.
            </div>
          )}
          {Boolean(mutationError) && (
            <div role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
              {apiMessage(mutationError, 'The takeover request failed.')}
            </div>
          )}
        </div>
      )}

      {canViewAudit && (
        <div className="mt-5 grid gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
            Takeover history
          </div>
          <AuditPanel sessions={auditQuery.data ?? []} />
        </div>
      )}
    </section>
  )
}
