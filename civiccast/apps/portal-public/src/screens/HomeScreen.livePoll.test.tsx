// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'

// Capture the manifestUrl prop without pulling in hls.js (jsdom can't run it).
vi.mock('../HlsPlayer', () => ({
  HlsPlayer: ({ manifestUrl }: { manifestUrl: string }) => (
    <div data-testid="player-src">{manifestUrl}</div>
  ),
}))

const LOCAL = 'http://station.local/media/live/gov-ch12/playlist.m3u8'
const CDN = 'https://cdn.example.org/live/gov-ch12/playlist.m3u8'

function liveBody(manifestUrl: string) {
  return {
    state: 'on_air',
    live_session_id: 's1',
    channel_id: 'gov-ch12',
    title: 'Council',
    started_at: null,
    manifest_url: manifestUrl,
  }
}

let currentCalls = 0

beforeEach(() => {
  currentCalls = 0
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    if (url.startsWith('/api/public/live/current')) {
      currentCalls += 1
      // The first resolution hands the local URL; the surge switch flips the
      // channel to its CDN URL, which the next poll should pick up.
      return json(liveBody(currentCalls <= 1 ? LOCAL : CDN))
    }
    if (url.startsWith('/api/public/schedule/coming-up')) return json([])
    if (url.startsWith('/api/public/assets')) return json([])
    return json({}) // idle page, submission agreement, emergency overlay, etc.
  }) as unknown as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('HomeScreen live re-resolve', () => {
  it('re-polls /current and swaps the player source to the CDN URL', async () => {
    render(<HomeScreen />)

    // Initial resolution: the player is handed the local manifest.
    const player = await screen.findByTestId('player-src')
    expect(player.textContent).toBe(LOCAL)

    // The periodic /current poll re-resolves and the player follows to the CDN
    // URL. Real timer + a generous findBy timeout, so no fake-timer fragility.
    const swapped = await screen.findByText(CDN, undefined, { timeout: 8000 })
    expect(swapped.textContent).toBe(CDN)
    expect(currentCalls).toBeGreaterThan(1) // proves it actually re-polled
  }, 12000)
})
