import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  ApiError,
  approveActivityPubFollower,
  blockActivityPubFollower,
  generateActivityPubStationKey,
  getActivityPubStatus,
  listActivityPubDeliveries,
  listActivityPubDeliveryRetries,
  listActivityPubFollowers,
  listActivityPubOutbox,
  rejectActivityPubFollower,
  replayActivityPubDeliveryRetry,
} from '../api/client'
import { ConfirmDialog, type PendingConfirm } from '../components/ConfirmDialog'
import { manualLink } from './manual-link'
import type {
  ActivityPubStatusResponse,
  DeliveryRecord,
  DeliveryRetryRecord,
  FollowerRecord,
  OutboxRecord,
} from '../types/api.generated'

type FollowerStatus = FollowerRecord['status']
type ModerationAction = 'approve' | 'reject' | 'block'

const FILTERS: ReadonlyArray<{ id: FollowerStatus; label: string }> = [
  { id: 'pending', label: 'Pending' },
  { id: 'accepted', label: 'Accepted' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'rejected', label: 'Rejected' },
  { id: 'removed', label: 'Removed' },
]

const STATUS_TONE: Record<FollowerStatus, { bg: string; fg: string }> = {
  pending: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  accepted: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  blocked: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
  rejected: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
  removed: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function StatusPill({ status }: { status: FollowerStatus }) {
  const tone = STATUS_TONE[status]
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {status}
    </span>
  )
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const apiError = error instanceof ApiError ? error : null
  return (
    <div
      role="alert"
      className="mx-6 my-6 grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
    >
      <div className="text-sm font-semibold">Could not load federation status.</div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {apiError?.detail ?? error.message}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong> Retry the request. If it fails again, check the API server logs and staff-token state.
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="w-fit rounded-md px-3 py-1.5 text-xs font-medium"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        Retry
      </button>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="mx-6 my-6 grid gap-3">
      {[0, 1, 2].map((item) => (
        <div
          key={item}
          className="h-28 animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

export function DisabledPanel({ status }: { status: ActivityPubStatusResponse }) {
  const [copied, setCopied] = useState(false)
  const [confirmingGenerate, setConfirmingGenerate] = useState(false)
  const mutation = useMutation({
    mutationFn: generateActivityPubStationKey,
    onSuccess: () => setCopied(false),
  })
  const result = mutation.data

  const copyEnvSettings = async () => {
    if (!result) return
    const text = Object.entries(result.env_settings)
      .map(([key, value]) => `${key}=${value}`)
      .join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section
      aria-label="Federation disabled"
      className="mx-6 grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">Federation is off</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            The station actor is not advertised and the public inbox is unavailable.
          </p>
        </div>
        <span
          className="rounded-full px-2 py-1 text-[11px] font-semibold"
          style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}
        >
          Default-safe
        </span>
      </div>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Federation lets other services that speak the ActivityPub protocol &mdash; the network
        behind Mastodon and similar sites, sometimes called &quot;the fediverse&quot; &mdash;
        follow this station and see when a new meeting is published, the same way someone
        might follow a page on a social network. <strong>Most stations do not need this</strong>{' '}
        and can leave it off.{' '}
        <Link to={manualLink('provider-federation')} style={{ color: 'var(--cc-brand)' }}>
          Read more in the manual
        </Link>
        .
      </p>
      {status.has_station_key && !result && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          A station key already exists on disk. Generating again reuses it &mdash; it will not
          create a second, different identity.
        </p>
      )}
      <div>
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => setConfirmingGenerate(true)}
          className="rounded-md px-4 py-2 text-sm font-semibold"
          style={{
            background: mutation.isPending ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
            color: mutation.isPending ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
          }}
        >
          {mutation.isPending ? 'Generating...' : 'Generate station key'}
        </button>
      </div>
      {confirmingGenerate && (
        <ConfirmDialog
          title="Generate the station key?"
          body={
            status.has_station_key
              ? 'A station key already exists on disk, so generating reuses it — the station keeps the same federation identity.'
              : "This creates the station's permanent federation identity key on disk. Other fediverse services will recognize the station by this key once federation is enabled."
          }
          confirmLabel="Generate key"
          tone="brand"
          onConfirm={() => {
            setConfirmingGenerate(false)
            mutation.mutate()
          }}
          onCancel={() => setConfirmingGenerate(false)}
        />
      )}
      {mutation.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {mutation.error instanceof ApiError
            ? mutation.error.detail ?? mutation.error.message
            : 'The station key could not be generated.'}
        </div>
      )}
      {result && (
        <div className="grid gap-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)' }}>
          <p className="m-0 font-semibold" style={{ color: 'var(--cc-ink)' }}>
            {result.already_existed ? 'Station key found.' : 'Station key generated.'}
          </p>
          <p className="m-0" style={{ color: 'var(--cc-ink-2)' }}>
            {result.next_step}
          </p>
          <dl className="m-0 grid gap-1" style={{ color: 'var(--cc-ink-2)' }}>
            {Object.entries(result.env_settings).map(([key, value]) => (
              <div key={key} className="grid gap-0.5">
                <dt className="cc-mono text-[10px] font-semibold" style={{ color: 'var(--cc-ink-3)' }}>
                  {key}
                </dt>
                <dd className="cc-mono m-0 break-all">{value}</dd>
              </div>
            ))}
          </dl>
          <button
            type="button"
            onClick={copyEnvSettings}
            className="justify-self-start rounded-md px-3 py-2 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            {copied ? 'Copied' : 'Copy settings'}
          </button>
        </div>
      )}
    </section>
  )
}

function SummaryBand({ status }: { status: ActivityPubStatusResponse }) {
  const counts = status.followers
  const items = [
    ['Mode', status.mode],
    ['Pending', counts.pending],
    ['Accepted', counts.accepted],
    ['Blocked', counts.blocked],
    ['Rejected', counts.rejected],
    ['Removed', counts.removed],
    ['Outbox', status.outbox_items],
    ['Deliveries', status.delivery_attempts],
  ] as const
  return (
    <section
      aria-label="Federation summary"
      className="grid gap-2 px-6 pb-3 sm:grid-cols-4 lg:grid-cols-8"
    >
      {items.map(([label, value]) => (
        <div
          key={label}
          className="rounded-md p-3"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            {label}
          </div>
          <div className="cc-mono text-lg font-semibold">{value}</div>
        </div>
      ))}
    </section>
  )
}

function PolicyPanel({ status }: { status: ActivityPubStatusResponse }) {
  return (
    <section
      aria-label="Federation policy"
      className="mx-6 mb-3 grid gap-3 rounded-md p-4 md:grid-cols-3"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>Station actor</div>
        <div className="cc-mono mt-1 break-all text-xs">{status.actor_url ?? 'Not exposed'}</div>
      </div>
      <div>
        <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>Fetch policy</div>
        <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {status.authorized_fetch ? 'Signed fetch required' : 'Public actor and collection fetches'}
        </div>
      </div>
      <div>
        <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>Domain policy</div>
        <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Allow {status.allowed_instances.length || 0} / block {status.blocked_instances.length || 0}
        </div>
      </div>
    </section>
  )
}

function FollowerRow({
  follower,
  onAction,
  pendingAction,
}: {
  follower: FollowerRecord
  onAction: (action: ModerationAction, actor: string) => void
  pendingAction: string | null
}) {
  const busy = pendingAction === follower.actor
  return (
    <article
      className="grid gap-3 rounded-md p-3 lg:grid-cols-[1fr_auto]"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="cc-mono break-all text-xs font-semibold">{follower.actor}</span>
          <StatusPill status={follower.status} />
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
          <span>Domain {follower.domain}</span>
          <span>Created {fmtDate(follower.created_at)}</span>
          <span className="cc-mono">Key {follower.public_key_id}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        {follower.status === 'pending' && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction('approve', follower.actor)}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)', border: '1px solid var(--cc-line)' }}
            >
              Approve
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction('reject', follower.actor)}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink)', border: '1px solid var(--cc-line)' }}
            >
              Reject
            </button>
          </>
        )}
        {follower.status !== 'blocked' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAction('block', follower.actor)}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)', border: '1px solid var(--cc-line)' }}
          >
            Block
          </button>
        )}
      </div>
    </article>
  )
}

function FollowersPanel({
  followers,
  filter,
  onAction,
  pendingAction,
}: {
  followers: FollowerRecord[]
  filter: FollowerStatus
  onAction: (action: ModerationAction, actor: string) => void
  pendingAction: string | null
}) {
  if (followers.length === 0) {
    return (
      <div
        className="mx-6 my-4 rounded-md p-6 text-center text-xs"
        style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)', color: 'var(--cc-ink-2)' }}
      >
        No {filter} followers.
      </div>
    )
  }
  return (
    <section aria-label={`${filter} followers`} className="grid gap-3 px-6 py-4">
      {followers.map((follower) => (
        <FollowerRow
          key={follower.actor}
          follower={follower}
          onAction={onAction}
          pendingAction={pendingAction}
        />
      ))}
    </section>
  )
}

function DeliveryRetryPanel({ retries }: { retries: DeliveryRetryRecord[] }) {
  const queryClient = useQueryClient()
  const [replayError, setReplayError] = useState<string | null>(null)
  const replayMutation = useMutation({
    mutationFn: (retryId: string) => replayActivityPubDeliveryRetry(retryId),
    onSuccess: () => {
      setReplayError(null)
      void queryClient.invalidateQueries({ queryKey: ['activitypub-delivery-retries'] })
    },
    onError: (error) =>
      setReplayError(
        error instanceof ApiError ? (error.detail ?? error.message) : 'Replay failed.',
      ),
  })
  const interesting = retries.filter((row) => row.state !== 'delivered')
  return (
    <section
      aria-label="Delivery retry queue"
      className="mx-6 mb-6 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="m-0 text-sm font-semibold">Delivery retry queue</h2>
      <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Failed follower deliveries retry automatically with backoff. Dead
        letters used every attempt — fix the follower instance issue, then
        replay.
      </p>
      {replayError && (
        <p className="m-0 mt-2 text-xs" role="alert" style={{ color: 'var(--cc-err)' }}>
          {replayError}
        </p>
      )}
      <div className="mt-3 grid gap-2">
        {interesting.length === 0 ? (
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            No pending or dead-lettered deliveries.
          </div>
        ) : (
          interesting.slice(0, 8).map((row) => (
            <div
              key={row.retry_id}
              className="grid gap-1 rounded-md p-2"
              style={{ background: 'var(--cc-surface-2)' }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase">
                  {row.state === 'dead_letter' ? 'Dead letter' : 'Retrying'}
                </span>
                <span className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                  attempt {row.attempts} · HTTP {row.last_status_code}
                </span>
              </div>
              <div className="cc-mono break-all text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
                {row.inbox_url}
              </div>
              {row.state === 'dead_letter' && (
                <button
                  type="button"
                  onClick={() => replayMutation.mutate(row.retry_id)}
                  disabled={replayMutation.isPending}
                  className="mt-1 justify-self-start rounded-md px-3 py-1.5 text-[11px] font-semibold"
                  style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
                >
                  Replay delivery
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}

function EvidencePanel({
  outbox,
  deliveries,
}: {
  outbox: OutboxRecord[]
  deliveries: DeliveryRecord[]
}) {
  const recent = useMemo(() => outbox.slice(0, 4), [outbox])
  return (
    <section className="grid gap-3 px-6 pb-6 lg:grid-cols-2">
      <div
        className="rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="m-0 text-sm font-semibold">Outbox evidence</h2>
        <div className="mt-3 grid gap-2">
          {recent.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No local federation activities yet.</div>
          ) : (
            recent.map((record) => (
              <div key={record.activity_id} className="grid gap-1 rounded-md p-2" style={{ background: 'var(--cc-surface-2)' }}>
                <div className="cc-mono break-all text-[11px] font-semibold">{record.activity_id}</div>
                <div className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                  {String(record.activity.type ?? 'Activity')} / {fmtDate(record.created_at)}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
      <div
        className="rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="m-0 text-sm font-semibold">Delivery attempts</h2>
        <div className="mt-3 grid gap-2">
          {deliveries.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No signed delivery attempts recorded.</div>
          ) : (
            deliveries.slice(0, 4).map((delivery) => (
              <div key={delivery.delivery_id} className="grid gap-1 rounded-md p-2" style={{ background: 'var(--cc-surface-2)' }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="cc-mono text-[11px] font-semibold">{delivery.status_code}</span>
                  <span className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>{fmtDate(delivery.created_at)}</span>
                </div>
                <div className="cc-mono break-all text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>{delivery.inbox_url}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  )
}

export function ActivityPubScreen() {
  const [filter, setFilter] = useState<FollowerStatus>('pending')
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  const queryClient = useQueryClient()
  const statusQuery = useQuery({
    queryKey: ['activitypub-status'],
    queryFn: getActivityPubStatus,
    retry: false,
  })
  const followersQuery = useQuery({
    queryKey: ['activitypub-followers', filter],
    queryFn: () => listActivityPubFollowers(filter),
    retry: false,
    enabled: statusQuery.data?.enabled === true,
  })
  const outboxQuery = useQuery({
    queryKey: ['activitypub-outbox'],
    queryFn: listActivityPubOutbox,
    retry: false,
    enabled: statusQuery.data?.enabled === true,
  })
  const deliveriesQuery = useQuery({
    queryKey: ['activitypub-deliveries'],
    queryFn: () => listActivityPubDeliveries(),
    retry: false,
    enabled: statusQuery.data?.enabled === true,
  })
  const retriesQuery = useQuery({
    queryKey: ['activitypub-delivery-retries'],
    queryFn: listActivityPubDeliveryRetries,
    retry: false,
    enabled: statusQuery.data?.enabled === true,
  })
  const mutation = useMutation({
    mutationFn: ({ action, actor }: { action: ModerationAction; actor: string }) => {
      if (action === 'approve') return approveActivityPubFollower({ actor })
      if (action === 'reject') return rejectActivityPubFollower({ actor })
      return blockActivityPubFollower({ actor })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['activitypub-status'] })
      void queryClient.invalidateQueries({ queryKey: ['activitypub-followers'] })
      void queryClient.invalidateQueries({ queryKey: ['activitypub-outbox'] })
      void queryClient.invalidateQueries({ queryKey: ['activitypub-deliveries'] })
    },
  })

  const error = statusQuery.error ?? followersQuery.error ?? outboxQuery.error ?? deliveriesQuery.error
  const status = statusQuery.data

  return (
    <div className="flex flex-col">
      <header className="px-6 pb-4 pt-6">
        <div className="mb-1 text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Federation
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">ActivityPub federation</h1>
        <p className="mt-1 max-w-3xl text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Station follows, moderation, policy controls, and signed delivery evidence share one operator surface.
        </p>
      </header>

      {statusQuery.isLoading && <LoadingState />}
      {error && <ErrorState error={error} onRetry={() => void statusQuery.refetch()} />}
      {status && !status.enabled && <DisabledPanel status={status} />}
      {status?.enabled && (
        <>
          <SummaryBand status={status} />
          <PolicyPanel status={status} />
          <div className="flex flex-wrap items-center gap-2 px-6 py-3" style={{ borderBottom: '1px solid var(--cc-line)' }}>
            <div role="tablist" aria-label="Filter follower state" className="flex flex-wrap gap-1">
              {FILTERS.map((item) => {
                const active = filter === item.id
                const count = status.followers[item.id]
                return (
                  <button
                    key={item.id}
                    role="tab"
                    aria-selected={active}
                    type="button"
                    onClick={() => setFilter(item.id)}
                    className="rounded-md px-3 py-1.5 text-xs font-medium"
                    style={{
                      background: active ? 'var(--cc-ink)' : 'transparent',
                      color: active ? 'var(--cc-ink-inv)' : 'var(--cc-ink-2)',
                      border: '1px solid transparent',
                    }}
                  >
                    {item.label} <span className="cc-mono">{count}</span>
                  </button>
                )
              })}
            </div>
          </div>
          {followersQuery.isLoading && <LoadingState />}
          {followersQuery.isSuccess && (
            <FollowersPanel
              followers={followersQuery.data.followers}
              filter={filter}
              onAction={(action, actor) => {
                if (action === 'approve') {
                  mutation.mutate({ action, actor })
                  return
                }
                setPendingConfirm({
                  title: action === 'block' ? `Block ${actor}?` : `Reject ${actor}?`,
                  body:
                    action === 'block'
                      ? 'This blocks the follower permanently — it stops receiving future publish activity and cannot re-follow until unblocked.'
                      : 'This rejects the pending follow request. The instance stops receiving future publish activity from this station.',
                  confirmLabel: action === 'block' ? 'Block follower' : 'Reject follower',
                  run: () => mutation.mutate({ action, actor }),
                })
              }}
              pendingAction={mutation.isPending ? mutation.variables?.actor ?? null : null}
            />
          )}
          <DeliveryRetryPanel retries={retriesQuery.data?.delivery_retries ?? []} />
          <EvidencePanel
            outbox={outboxQuery.data?.outbox ?? []}
            deliveries={deliveriesQuery.data?.deliveries ?? []}
          />
          {mutation.error && (
            <div role="alert" className="mx-6 mb-6 rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              Federation moderation failed. Check the API logs, then retry the follower action.
            </div>
          )}
        </>
      )}
      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          tone={pendingConfirm.tone}
          onConfirm={() => {
            pendingConfirm.run()
            setPendingConfirm(null)
          }}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}
