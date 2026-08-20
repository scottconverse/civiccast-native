// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Resident channel guide (cable automation CA-5): what airs on each channel
// over the next few days, from the sanitized public program-log endpoint.

import { useEffect, useState } from 'react'
import { fetchJson, formatDuration } from '../api'
import { buildScheduleHash } from '../router'
import type { PortalChannelInfo, PortalStationConfig, PublicGuideEntry } from '../types'

// Guide fetch result keyed by channel: deriving the load state from whether
// the stored result matches the current channel avoids synchronous setState
// inside the effect (react-hooks/set-state-in-effect).
interface GuideResult {
  channel: string
  entries?: PublicGuideEntry[]
  error?: string
}

function formatGuideTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

function groupByDay(entries: PublicGuideEntry[]): Array<{ day: Date; entries: PublicGuideEntry[] }> {
  const map = new Map<string, { day: Date; entries: PublicGuideEntry[] }>()
  for (const entry of entries) {
    const d = new Date(entry.starts_at)
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    const existing = map.get(key)
    if (existing) {
      existing.entries.push(entry)
    } else {
      const day = new Date(d)
      day.setHours(0, 0, 0, 0)
      map.set(key, { day, entries: [entry] })
    }
  }
  const groups = Array.from(map.values())
  groups.sort((a, b) => a.day.getTime() - b.day.getTime())
  return groups
}

export function ChannelGuideScreen({ channel }: { channel: string }) {
  const [result, setResult] = useState<GuideResult | null>(null)
  const [channels, setChannels] = useState<PortalChannelInfo[]>([])
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    // Channel tabs are best-effort; the guide itself is the load-bearing call.
    fetchJson<PortalStationConfig>('/api/public/app/config')
      .then((config) => {
        if (!cancelled) setChannels(config.channels ?? [])
      })
      .catch(() => {
        if (!cancelled) setChannels([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchJson<PublicGuideEntry[]>(
      `/api/public/programlog/channels/${encodeURIComponent(channel)}/guide?hours=72`,
    )
      .then((entries) => {
        if (!cancelled) setResult({ channel, entries })
      })
      .catch((error: Error) => {
        if (!cancelled) setResult({ channel, error: error.message })
      })
    return () => {
      cancelled = true
    }
  }, [channel, retryKey])

  function retryLoad() {
    setResult(null)
    setRetryKey((value) => value + 1)
  }

  const current = result?.channel === channel ? result : null
  const state: 'loading' | 'ready' | 'error' =
    current == null ? 'loading' : current.error != null ? 'error' : 'ready'
  const entries = current?.entries ?? []
  const errorMessage = current?.error ?? ''
  const groups = groupByDay(entries)
  const tabChannels: PortalChannelInfo[] =
    channels.length > 0
      ? channels
      : [{ channel_id: channel, branding: { display_name: channel } }]

  return (
    <section aria-labelledby="schedule-heading" className="space-y-4">
      <div>
        <h2 id="schedule-heading" tabIndex={-1} className="text-xl font-semibold">
          Channel schedule
        </h2>
        <p className="text-sm text-stone-300">
          What airs over the next three days. Times are shown in your local
          timezone.
        </p>
      </div>

      <nav aria-label="Channels" className="flex flex-wrap gap-2">
        {tabChannels.map((c) => {
          const current = c.channel_id === channel
          return (
            <a
              key={c.channel_id}
              href={buildScheduleHash(c.channel_id)}
              aria-current={current ? 'page' : undefined}
              className={`inline-flex min-h-11 items-center rounded-md border px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-200 ${
                current
                  ? 'border-emerald-300/80 bg-emerald-300/10 text-emerald-100'
                  : 'border-stone-500/60 text-stone-100 hover:border-emerald-300/60'
              }`}
            >
              {c.branding.display_name}
            </a>
          )
        })}
      </nav>

      {state === 'loading' && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-200"
        >
          Loading the channel schedule.
        </div>
      )}

      {state === 'error' && (
        <div
          role="alert"
          className="rounded-lg border border-red-400/50 bg-red-950/40 p-5 text-sm text-red-100"
        >
          <p>
            The schedule could not be loaded. {errorMessage} Try again, then contact the
            station if the problem continues.
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

      {state === 'ready' && entries.length === 0 && (
        <p className="rounded-lg border border-dashed border-stone-500 bg-[#172018] p-4 text-sm text-stone-300">
          Nothing is on the schedule for this channel yet. Check back soon.
        </p>
      )}

      {state === 'ready' &&
        groups.map((group) => (
          <div key={group.day.toISOString()} className="space-y-2">
            <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-emerald-200">
              {new Intl.DateTimeFormat(undefined, {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
              }).format(group.day)}
            </h3>
            <ul className="divide-y divide-white/10 rounded-lg border border-stone-500/30 bg-[#172018]">
              {group.entries.map((entry) => {
                // Audit UX-008: mark the entry airing right now so a
                // resident can answer "what's on?" at a glance.
                const startsMs = new Date(entry.starts_at).getTime()
                const onNow =
                  entry.duration_seconds != null &&
                  Date.now() >= startsMs &&
                  Date.now() < startsMs + entry.duration_seconds * 1000
                return (
                  <li
                    key={`${entry.starts_at}-${entry.title}`}
                    className={`flex flex-wrap items-baseline gap-x-4 gap-y-1 p-4${
                      onNow ? ' border-l-4 border-emerald-300/80 bg-emerald-300/5' : ''
                    }`}
                  >
                    <span className="w-20 shrink-0 text-sm font-semibold text-stone-100">
                      {formatGuideTime(entry.starts_at)}
                    </span>
                    <span className="min-w-0 flex-1 text-sm font-medium text-stone-50">
                      {entry.title}
                      {onNow && (
                        <span className="ml-2 rounded bg-emerald-300/20 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-100">
                          On now
                        </span>
                      )}
                    </span>
                    <span className="text-xs text-stone-400">
                      {formatDuration(entry.duration_seconds)}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
    </section>
  )
}
