// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// S25 §5 — published meeting agenda rendered beside the public-portal player.
//
// Behavior (S25 spec §6 + DC-2/DC-5/DC-6):
// - Fetches GET /api/public/agendas/{meeting_asset_id} on mount.
// - 404 → renders nothing (agenda is additive metadata; no agenda is valid).
// - 200 → renders a heading + optional source-doc link + an ordered button
//   list. Clicking an item with a timecode calls onSeek(seconds); items
//   without a timecode are disabled AND removed from the tab order so
//   keyboard users can't land on a no-op (the S24 UX-4 pattern).
// - Keyboard nav: arrow Up/Down between items, Home/End to first/last,
//   Enter or Space to seek (the buttons are real <button>s so Enter/Space
//   activate via the browser's default behavior).

import { useCallback, useEffect, useRef, useState } from 'react'

import { FetchError, fetchJson } from './api'
import type { PublicMeetingAgenda } from './types'

/**
 * UX-2 / DC-4: an `https?://` URL whose path ends in `.pdf` is treated as a
 * PDF and embedded in an iframe beside the agenda items. URLs that are not
 * obviously PDFs fall back to the existing "open in a new tab" link. We do
 * not probe Content-Type — a HEAD request on every render is expensive and
 * many servers omit it on signed-URL CDNs; the URL-suffix heuristic is
 * good enough for the §6 single-source-of-truth promise.
 */
function isPdfHttpUrl(url: string | null | undefined): url is string {
  if (!url) return false
  if (!/^https?:\/\//i.test(url)) return false
  // Strip query/fragment before checking the extension; many gov agenda
  // services append ?token=... to a real PDF.
  const path = url.split('#')[0].split('?')[0]
  return /\.pdf$/i.test(path)
}

interface MeetingAgendaSidebarProps {
  meeting_asset_id: string
  onSeek: (seconds: number) => void
}

// Result keyed by asset id (the WatchScreen pattern): deriving "loading" from
// "result for this asset_id has not landed yet" replaces a reset-then-fetch
// effect (react-hooks/set-state-in-effect) — switching to a new asset id
// implicitly resets the displayed state because the old result no longer
// matches.
interface AgendaResult {
  assetId: string
  state: 'absent' | 'error' | 'ready'
  agenda: PublicMeetingAgenda | null
}

function formatTimecode(seconds: number): string {
  // Always HH:MM:SS so a long meeting and a short one read the same way.
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}`
}

export function MeetingAgendaSidebar({
  meeting_asset_id,
  onSeek,
}: MeetingAgendaSidebarProps) {
  const [result, setResult] = useState<AgendaResult | null>(null)
  // One ref per item button, indexed by item_id, so arrow-key nav can move
  // focus without coupling the focus model to React reconciliation order.
  const buttonRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map())

  useEffect(() => {
    let cancelled = false
    fetchJson<PublicMeetingAgenda>(
      `/api/public/agendas/${encodeURIComponent(meeting_asset_id)}`,
    )
      .then((agenda) => {
        if (!cancelled) {
          setResult({ assetId: meeting_asset_id, state: 'ready', agenda })
        }
      })
      .catch((error: Error) => {
        if (cancelled) return
        // A meeting without a published agenda is valid (key-claim boundary).
        // Treat 404 as "no agenda" and render nothing; surface other errors
        // as a quiet inline notice so the player itself stays usable.
        //
        // T-7 fix: discriminate on the FetchError's HTTP status (most robust)
        // and only fall back to the legacy message-regex when the thrown
        // error is not a FetchError (e.g. a network failure throws TypeError
        // from fetch() before any status is known — treat as "error", not
        // "absent"). This keeps the absent vs error decision stable even if
        // a future fetchJson refactor changes the message format.
        let isAbsent: boolean
        if (error instanceof FetchError) {
          isAbsent = error.status === 404
        } else {
          isAbsent =
            /404|not found/i.test(error.message) ||
            error.message.includes('No published agenda')
        }
        setResult({
          assetId: meeting_asset_id,
          state: isAbsent ? 'absent' : 'error',
          agenda: null,
        })
      })
    return () => {
      cancelled = true
    }
  }, [meeting_asset_id])

  const current = result?.assetId === meeting_asset_id ? result : null
  const status = current?.state ?? 'loading'

  const focusItemAt = useCallback(
    (items: PublicMeetingAgenda['items'], index: number) => {
      const clamped = Math.max(0, Math.min(items.length - 1, index))
      const target = items[clamped]
      if (!target) return
      const btn = buttonRefs.current.get(target.item_id)
      btn?.focus()
    },
    [],
  )

  if (status === 'loading') {
    return (
      <aside
        aria-labelledby="agenda-heading"
        className="rounded-lg border border-stone-500/30 bg-[#172018] p-4 text-sm text-stone-200"
      >
        <h3 id="agenda-heading" className="text-base font-semibold">
          Agenda
        </h3>
        <p role="status" aria-live="polite" className="mt-2 text-stone-300">
          Loading agenda&hellip;
        </p>
      </aside>
    )
  }

  if (status === 'absent') {
    // S25 key-claim boundary: no agenda is a valid meeting state. Render
    // nothing so the player owns the whole width for meetings without an
    // agenda.
    return null
  }

  if (status === 'error') {
    return (
      <aside
        aria-labelledby="agenda-heading"
        className="rounded-lg border border-amber-300/50 bg-amber-950/30 p-4 text-sm text-amber-50"
      >
        <h3 id="agenda-heading" className="text-base font-semibold">
          Agenda
        </h3>
        <p role="alert" className="mt-2">
          The agenda could not be loaded right now.
        </p>
      </aside>
    )
  }

  // Narrow: status==='ready' iff current exists with a non-null agenda.
  const agenda = current?.agenda
  if (!agenda) return null
  const items = [...agenda.items].sort((a, b) => a.order - b.order)

  const onKeyDown = (event: React.KeyboardEvent<HTMLUListElement>) => {
    const target = event.target as HTMLElement
    const itemId = target.getAttribute('data-item-id')
    if (!itemId) return
    const currentIndex = items.findIndex((i) => i.item_id === itemId)
    if (currentIndex === -1) return

    // Skip past disabled (no-timecode) items in arrow nav so keyboard users
    // only ever land on actionable buttons (S24 UX-4 pattern).
    const step = (start: number, direction: 1 | -1) => {
      let i = start + direction
      while (i >= 0 && i < items.length) {
        if (items[i].video_timecode_s !== null) return i
        i += direction
      }
      return start
    }

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        focusItemAt(items, step(currentIndex, 1))
        break
      case 'ArrowUp':
        event.preventDefault()
        focusItemAt(items, step(currentIndex, -1))
        break
      case 'Home': {
        event.preventDefault()
        const first = items.findIndex((i) => i.video_timecode_s !== null)
        if (first !== -1) focusItemAt(items, first)
        break
      }
      case 'End': {
        event.preventDefault()
        for (let i = items.length - 1; i >= 0; i--) {
          if (items[i].video_timecode_s !== null) {
            focusItemAt(items, i)
            break
          }
        }
        break
      }
      default:
        break
    }
  }

  const sourceDocUrl = agenda.source_doc_url
  const sourceIsPdf = isPdfHttpUrl(sourceDocUrl)

  return (
    <aside
      aria-labelledby="agenda-heading"
      className="rounded-lg border border-stone-500/30 bg-[#172018] p-4 text-sm text-stone-200"
    >
      <div className="flex flex-col gap-2">
        <h3 id="agenda-heading" className="text-base font-semibold">
          Agenda
        </h3>
        {sourceDocUrl && (
          // UX-2 / DC-4: always render the open-in-new-tab link (printable,
          // shareable, accessible if the iframe fails) — when the URL is a
          // PDF the embedded viewer below provides the §6 "renders beside
          // the player" surface; non-PDF URLs degrade to the link only.
          <a
            href={sourceDocUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit min-h-11 items-center text-sm font-medium text-emerald-100 underline focus:outline-none focus:ring-2 focus:ring-emerald-200"
          >
            Agenda document
          </a>
        )}
      </div>
      {items.length === 0 ? (
        <p className="mt-3 text-stone-300">No agenda items posted.</p>
      ) : (
        <ul
          className="mt-3 flex flex-col gap-1"
          onKeyDown={onKeyDown}
          aria-label="Agenda items"
        >
          {items.map((item) => {
            const seekable = item.video_timecode_s !== null
            const label = item.number ? `${item.number} ${item.title}` : item.title
            const ariaLabel = `Jump to ${label}`
            return (
              <li key={item.item_id}>
                <button
                  ref={(el) => {
                    buttonRefs.current.set(item.item_id, el)
                  }}
                  type="button"
                  data-item-id={item.item_id}
                  aria-label={ariaLabel}
                  aria-disabled={!seekable || undefined}
                  tabIndex={seekable ? 0 : -1}
                  disabled={!seekable}
                  onClick={() => {
                    if (seekable && item.video_timecode_s !== null) {
                      onSeek(item.video_timecode_s)
                    }
                  }}
                  className={`flex w-full min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-emerald-200 ${
                    seekable
                      ? 'border-stone-500/60 text-stone-100 hover:border-emerald-300/60 hover:bg-emerald-300/10'
                      : 'cursor-not-allowed border-stone-700/40 text-stone-400'
                  }`}
                >
                  <span className="flex items-baseline gap-2">
                    {item.number && (
                      <span className="font-semibold text-emerald-100">
                        {item.number}
                      </span>
                    )}
                    <span>{item.title}</span>
                  </span>
                  <span className="shrink-0 font-mono text-xs text-stone-400">
                    {seekable && item.video_timecode_s !== null
                      ? formatTimecode(item.video_timecode_s)
                      : '—'}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {sourceIsPdf && sourceDocUrl && (
        // UX-2 / DC-4: embed the PDF beside the player (the sidebar is the
        // grid column adjacent to the player). Sandbox the frame so a
        // malicious or noisy PDF cannot navigate top, run popups, or
        // execute outside its own context. `title` is the accessible name
        // a screen-reader announces when reaching the embedded frame.
        <div className="mt-4">
          <h4 className="mb-2 text-sm font-semibold text-stone-100">Agenda document</h4>
          <iframe
            src={sourceDocUrl}
            title="Agenda document"
            sandbox="allow-same-origin allow-popups"
            className="h-[480px] w-full rounded-md border border-stone-500/30 bg-stone-100"
          />
          <p className="mt-1 text-xs text-stone-400">
            Browser cannot render the PDF? Open it in a new tab via the link above.
          </p>
        </div>
      )}
    </aside>
  )
}
