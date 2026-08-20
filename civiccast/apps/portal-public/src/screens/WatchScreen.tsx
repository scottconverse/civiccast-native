// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Recording detail page with a canonical shareable URL (#/watch/{asset_id}).

import { useEffect, useRef, useState } from 'react'
import { fetchJson, formatDateTime, formatDuration } from '../api'
import { HlsPlayer, type HlsPlayerHandle } from '../HlsPlayer'
import { MeetingAgendaSidebar } from '../MeetingAgendaSidebar'
import { PaywallGate } from '../PaywallGate'
import { buildRecordingsHash } from '../router'
import type { AssetMetadata } from '../types'

// Fetch result keyed by asset id: deriving the view state from whether the
// stored result matches the current asset replaces the old reset-then-fetch
// effect (react-hooks/set-state-in-effect) and the copied flag resets for
// free when the route changes.
interface WatchResult {
  assetId: string
  asset: AssetMetadata | null
  state: 'ready' | 'not_found' | 'error'
}

export function WatchScreen({ assetId }: { assetId: string }) {
  const [result, setResult] = useState<WatchResult | null>(null)
  const [copiedFor, setCopiedFor] = useState<string | null>(null)
  const [retryKey, setRetryKey] = useState(0)
  // S25 §6: agenda items seek the player via this imperative handle. The
  // HlsPlayer publishes a seekTo on mount; MeetingAgendaSidebar invokes it
  // through the onSeek callback below.
  const playerHandleRef = useRef<HlsPlayerHandle | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchJson<AssetMetadata>(`/api/public/assets/${encodeURIComponent(assetId)}`)
      .then((asset) => {
        if (!cancelled) setResult({ assetId, asset, state: 'ready' })
      })
      .catch((error: Error) => {
        if (cancelled) return
        setResult({
          assetId,
          asset: null,
          state: error.message.includes('not found') ? 'not_found' : 'error',
        })
      })
    return () => {
      cancelled = true
    }
  }, [assetId, retryKey])

  const current = result?.assetId === assetId ? result : null
  const state = current?.state ?? 'loading'
  const asset = current?.asset ?? null
  const copied = copiedFor === assetId

  function retryLoad() {
    setResult(null)
    setRetryKey((value) => value + 1)
  }

  async function copyShareLink() {
    const canonical = `${window.location.origin}${window.location.pathname}#/watch/${encodeURIComponent(assetId)}`
    try {
      await navigator.clipboard.writeText(canonical)
      setCopiedFor(assetId)
    } catch {
      // Clipboard can be unavailable (permissions, http); show the URL instead.
      window.prompt('Copy this link to share the recording:', canonical)
    }
  }

  return (
    <section aria-labelledby="watch-heading" className="space-y-4">
      <a
        href={buildRecordingsHash({})}
        className="inline-flex min-h-11 items-center text-sm font-medium text-emerald-100 underline focus:outline-none focus:ring-2 focus:ring-emerald-200"
      >
        Back to all recordings
      </a>

      {state === 'loading' && (
        <p
          role="status"
          aria-live="polite"
          className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-200"
        >
          Loading this recording.
        </p>
      )}

      {state === 'not_found' && (
        <section
          role="alert"
          className="rounded-lg border border-amber-300/50 bg-amber-950/30 p-5 text-sm text-amber-50"
        >
          <h2 id="watch-heading" tabIndex={-1} className="text-xl font-semibold">
            Recording not found
          </h2>
          <p className="mt-2">
            This recording does not exist or is no longer published. Browse the
            archive for the current recordings.
          </p>
        </section>
      )}

      {state === 'error' && (
        <div
          role="alert"
          className="rounded-lg border border-red-400/50 bg-red-950/40 p-5 text-sm text-red-100"
        >
          <p>
            This recording could not be loaded right now. Try again, then contact the station if
            the problem continues.
          </p>
          <button
            type="button"
            onClick={retryLoad}
            className="mt-3 min-h-11 rounded-md border border-red-200/70 px-4 py-2 font-semibold hover:bg-red-200/10 focus:outline-none focus:ring-2 focus:ring-red-100"
          >
            Retry
          </button>
        </div>
      )}

      {state === 'ready' && asset && (
        <article className="space-y-4">
          <header>
            <h2 id="watch-heading" tabIndex={-1} className="text-2xl font-semibold">
              {asset.title}
            </h2>
            <p className="mt-1 text-sm text-stone-400">
              Published {formatDateTime(asset.published_at)} /{' '}
              {formatDuration(asset.duration_seconds)}
            </p>
          </header>
          {/* S25 §5: 2-column grid at lg+ (player on the left, agenda sidebar
             on the right); stacks vertically below lg so phones get a single
             full-width column. The sidebar renders nothing on a 404, so the
             grid collapses to a single-column visual for meetings with no
             agenda. The sidebar max width is generous (440px) so the DC-4
             PDF iframe rendered inside the sidebar (UX-2 fix) is readable
             without crowding the player on narrower desktops. */}
          {/* S26 §6 + §9: wrap ONLY the player in the paywall gate; the
             MeetingAgendaSidebar (S25) sits OUTSIDE so a paywalled meeting
             still shows its public agenda. When the deployment has no
             paywall configured the gate's access check returns allowed=true
             and the player renders unchanged (DC-1 default-off). */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_minmax(320px,440px)]">
            <PaywallGate assetId={asset.asset_id}>
              <HlsPlayer
                manifestUrl={asset.manifest_url}
                analytics={{ contentId: asset.asset_id }}
                handleRef={playerHandleRef}
              />
            </PaywallGate>
            <MeetingAgendaSidebar
              meeting_asset_id={asset.asset_id}
              onSeek={(seconds) => playerHandleRef.current?.seekTo(seconds)}
            />
          </div>
          <p className="max-w-3xl text-sm leading-6 text-stone-300">
            {asset.description ?? 'Recording description not posted.'}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={copyShareLink}
              className="min-h-11 rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            >
              Copy share link
            </button>
            {copied && (
              <span role="status" aria-live="polite" className="text-sm text-emerald-200">
                Link copied.
              </span>
            )}
          </div>
        </article>
      )}
    </section>
  )
}
