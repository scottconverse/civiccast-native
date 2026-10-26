// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useEffect, useState } from 'react'
import { fetchJson } from '../api'
import type { PortalChannelInfo, PortalStationConfig } from '../types'

// The live sidecar is a rolling window, not a recording or reviewed transcript.
function captionLines(vtt: string): string[] {
  return vtt.split(/\r?\n\s*\r?\n/).filter((block) => block.includes('-->'))
    .map((block) => block.split(/\r?\n/).slice(block.split(/\r?\n/).findIndex((line) => line.includes('-->')) + 1)
      .join(' ').replace(/<[^>]*>/g, '').trim()).filter(Boolean).slice(-3)
}

export function CaptionDisplayScreen({ channel }: { channel: string }) {
  const [channels, setChannels] = useState<PortalChannelInfo[]>([])
  const [lines, setLines] = useState<string[]>([])
  const [message, setMessage] = useState('Waiting for caption input…')
  const [size, setSize] = useState(36)
  useEffect(() => {
    let disposed = false
    fetchJson<PortalStationConfig>('/api/public/app/config').then((config) => {
      if (!disposed) setChannels(config.channels)
    }).catch(() => { if (!disposed) setChannels([]) })
    return () => { disposed = true }
  }, [])
  useEffect(() => {
    let disposed = false
    let previous: string | null = null
    let observedChange = false
    let changedAt = Date.now()
    let running = false
    async function refresh() {
      if (running) return
      running = true
      try {
        const response = await fetch(`/api/public/channels/${encodeURIComponent(channel)}/captions.vtt`, { cache: 'no-store' })
        if (!response.ok) throw new Error('unavailable')
        const text = await response.text()
        if (disposed) return
        if (text !== previous) {
          if (previous !== null) observedChange = true
          previous = text; changedAt = Date.now()
        }
        const next = captionLines(text)
        if (Date.now() - changedAt > 30_000) {
          setLines([]); setMessage('No new caption input for 30 seconds. Waiting for the channel to resume captions.')
        } else {
          setLines(next); setMessage(next.length ? (observedChange ? 'Receiving new live captions' : 'Latest available captions; waiting for new input') : 'Captions are not available yet. Waiting for channel input…')
        }
      } catch {
        if (!disposed) { setLines([]); setMessage('Captions are unavailable or input was interrupted. Retrying…') }
      } finally { running = false }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [channel])
  const options = channels.length ? channels : [{ channel_id: channel, branding: { display_name: channel } }]
  const link = `${window.location.origin}${window.location.pathname}#/captions?channel=${encodeURIComponent(channel)}`
  return <section className="grid gap-4" aria-labelledby="caption-display-title">
    <h2 id="caption-display-title" tabIndex={-1} className="text-2xl font-semibold">Live caption display</h2>
    <label>Public channel <select aria-label="Caption display channel" value={channel}
      onChange={(event) => { window.location.hash = `/captions?channel=${encodeURIComponent(event.target.value)}` }}>
      {options.map((item) => <option key={item.channel_id} value={item.channel_id}>{item.branding.display_name}</option>)}
    </select></label>
    <p>English live captions are automatic and may contain errors. This display is not the approved official record.
      Live translation into other languages is unavailable; reviewed translated tracks are offered on recordings.</p>
    <label>Text size <input aria-label="Caption text size" type="range" min="24" max="72" step="4" value={size}
      onChange={(event) => setSize(Number(event.target.value))} /> {size}px</label>
    <p role="status">{message}</p>
    <div role="log" aria-label="Live caption text" aria-live="polite" aria-relevant="text" style={{ fontSize: size, lineHeight: 1.5 }}>
      {lines.map((line, index) => <p key={`${index}-${line}`} dir="auto">{line}</p>)}
    </div>
    <a href={link}>Open this channel’s caption display on a phone or browser</a>
  </section>
}
