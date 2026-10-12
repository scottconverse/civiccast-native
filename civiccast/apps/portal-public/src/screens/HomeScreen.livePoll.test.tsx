// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'
import { COMING_UP_POLL_SECONDS } from './homeLive'
import type { ScheduleItem } from '../types'

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

  it('refreshes Coming Up so a premiere that has started is removed while Home stays open', async () => {
    const upcoming: ScheduleItem = {
      id: 'premiere-1',
      asset_id: 'council-recording',
      asset_title: 'Council recording',
      channel_id: 'public',
      mode: 'premiere',
      state: 'published',
      scheduled_at: '2026-10-12T20:00:00Z',
      duration_seconds: 3600,
    }
    let scheduleCalls = 0
    let refreshSchedule: TimerHandler | undefined
    let intervalId = 0
    vi.spyOn(window, 'setInterval').mockImplementation((handler, timeout) => {
      if (timeout === COMING_UP_POLL_SECONDS * 1000) refreshSchedule = handler
      intervalId += 1
      return intervalId
    })
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/public/live/current')) {
        return json({
          state: 'offline',
          live_session_id: null,
          channel_id: null,
          title: null,
          started_at: null,
          manifest_url: null,
        })
      }
      if (url.startsWith('/api/public/schedule/coming-up')) {
        scheduleCalls += 1
        return json(scheduleCalls === 1 ? [upcoming] : [])
      }
      if (url.startsWith('/api/public/assets')) return json([])
      return json({})
    }) as unknown as typeof fetch

    render(<HomeScreen />)
    expect(await screen.findByText('Council recording')).toBeTruthy()
    expect(typeof refreshSchedule).toBe('function')

    await act(async () => {
      if (typeof refreshSchedule === 'function') refreshSchedule()
    })

    expect(await screen.findByText('No premieres are scheduled.')).toBeTruthy()
    expect(screen.queryByText('Council recording')).toBeNull()
    expect(scheduleCalls).toBe(2)
  })
})
