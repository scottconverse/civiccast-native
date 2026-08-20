// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S6 feed-item approval queue (build step 9 slice 4b). For an approval-gated CG
// feed zone, the operator reviews the feed's current items and approves the ones
// that may show on the board. The list comes from the review endpoint (each
// CgFeedItem carries its real approved/pending status); approving uses the
// existing per-item approve endpoint. Split into a pure FeedApprovalList (tested
// with props) + a FeedApprovalQueue wrapper that owns the query/mutation.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, approveCgFeedItem, listCgFeedItemsForReview } from '../api/client'
import type { CgFeedItem } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

export function FeedApprovalList({
  items,
  canApprove,
  busyItemId,
  onApprove,
}: {
  items: CgFeedItem[]
  canApprove: boolean
  busyItemId: string | null
  onApprove: (itemId: string) => void
}) {
  if (items.length === 0) {
    return (
      <div className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
        No items in this feed right now.
      </div>
    )
  }
  const pending = items.filter((it) => !it.approved).length
  return (
    <div className="grid gap-1.5">
      <div className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
        {pending} pending · {items.length - pending} approved
      </div>
      {items.map((item) => (
        <div
          key={item.item_id}
          className="flex items-start justify-between gap-2 rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          <div className="min-w-0">
            <div className="font-medium" style={{ color: 'var(--cc-ink)' }}>{item.title}</div>
            {item.summary && (
              <div className="truncate text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>{item.summary}</div>
            )}
          </div>
          {item.approved ? (
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ok)' }}
            >
              Approved
            </span>
          ) : canApprove ? (
            <button
              type="button"
              onClick={() => onApprove(item.item_id)}
              disabled={busyItemId === item.item_id}
              className="shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              Approve
            </button>
          ) : (
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
            >
              Pending
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

export function FeedApprovalQueue({
  channelId,
  feedSourceId,
  canApprove,
}: {
  channelId: string
  feedSourceId: string
  canApprove: boolean
}) {
  const qc = useQueryClient()
  const itemsQuery = useQuery({
    queryKey: ['cg-feed-items', channelId, feedSourceId],
    queryFn: () => listCgFeedItemsForReview(channelId, feedSourceId),
  })
  const approve = useMutation({
    mutationFn: (itemId: string) => approveCgFeedItem(channelId, feedSourceId, itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cg-feed-items', channelId, feedSourceId] }),
    onError: () => {},
  })

  if (itemsQuery.isLoading) {
    return <div className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>Loading feed items…</div>
  }
  if (itemsQuery.isError) {
    return (
      <div className="text-[11px]" style={{ color: 'var(--cc-err)' }}>
        {apiMessage(itemsQuery.error, 'Could not load feed items.')}
      </div>
    )
  }
  return (
    <div>
      <FeedApprovalList
        items={itemsQuery.data ?? []}
        canApprove={canApprove}
        busyItemId={approve.isPending ? (approve.variables ?? null) : null}
        onApprove={(itemId) => approve.mutate(itemId)}
      />
      {approve.isError && (
        <p className="mt-2 text-xs" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(approve.error, 'Could not approve this item. Try again.')}
        </p>
      )}
    </div>
  )
}
