// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'
import { LIVE_POLL_SECONDS } from './homeLive'

// Review round 2, MAJOR 3: a channel on its FALLBACK_SLATE used to arrive as
// `on_air`, so Home said "On air" for a slate and never showed the idle page.
// /api/public/live/current now reports `standing_by` for that case; Home must
// say so in plain words, must never say "On air", must keep the idle page up,
// and must not autoplay the slate manifest even though it is reported.

vi.mock('../HlsPlayer', () => ({
  HlsPlayer: ({ manifestUrl }: { manifestUrl: string }) => (
    <div data-testid="player-src">{manifestUrl}</div>
  ),
}))

type LiveBody = {
  state: string
  live_session_id: string | null
  channel_id: string | null
  title: string | null
  started_at: string | null
  manifest_url: string | null
  reason: string | null
}

let liveBody: LiveBody
let idlePageBody: unknown

beforeEach(() => {
  idlePageBody = null
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString()
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    if (url.startsWith('/api/public/live/current')) return json(liveBody)
    if (url.startsWith('/api/public/schedule/coming-up')) return json([])
    if (url.startsWith('/api/public/assets')) return json([])
    if (url.startsWith('/api/public/cg/idle')) return json(idlePageBody)
    return json({}) // submission agreement, emergency overlay, etc.
  }) as unknown as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const standingBy: LiveBody = {
  state: 'standing_by',
  live_session_id: null,
  channel_id: 'public',
  title: 'Slate',
  started_at: '2026-09-08T18:00:00+00:00',
  manifest_url: '/media/live/public/playlist.m3u8',
  reason: 'fallback slate, no program on air',
}

describe('HomeScreen when the channel is standing by on its slate', () => {
  it('says "Standing by", never "On air", and does not autoplay the slate', async () => {
    liveBody = standingBy
    render(<HomeScreen />)

    expect(
      await screen.findByText('The station is standing by. No program is on air right now.'),
    ).toBeTruthy()
    expect(screen.getByText('Standing by')).toBeTruthy()
    expect(screen.queryByText('On air')).toBeNull()
    expect(screen.queryByText('On air (no web preview)')).toBeNull()
    expect(screen.queryByText('Offline')).toBeNull()
    expect(screen.queryByText('Slate is on air.')).toBeNull()
    expect(screen.queryByTestId('player-src')).toBeNull()
    // A station standing by is not an empty station (review round 2 delta,
    // MINOR 6): the live card already says what is happening.
    expect(screen.queryByText(/Nothing is posted yet/)).toBeNull()
  })

  it('keeps the between-streams idle page up while standing by', async () => {
    liveBody = standingBy
    idlePageBody = {
      channel_id: 'public',
      title: 'Back soon',
      message: 'The next meeting starts at 6 pm.',
      next_broadcast_label: 'Council meeting, 6:00 pm',
      action_label: 'See the schedule',
      action_url: '/schedule',
    }
    render(<HomeScreen />)

    expect(await screen.findByText('Standing by')).toBeTruthy()
    expect(screen.getByLabelText('Between-streams idle page')).toBeTruthy()
    expect(screen.queryByTestId('player-src')).toBeNull()
  })

  it('starts the player only when the slate hands off to a real program', async () => {
    // The beta.5 walkthrough as residents see it: the channel idles on its
    // slate, then a program goes on air. The re-resolve poll flips the state
    // and the player must appear at THAT moment -- and not before. Without
    // the standing-by branch the first half fails: the slate autoplays.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    liveBody = standingBy
    render(<HomeScreen />)
    expect(await screen.findByText('Standing by')).toBeTruthy()
    expect(screen.queryByTestId('player-src')).toBeNull()

    liveBody = {
      ...standingBy,
      state: 'on_air',
      title: 'Council meeting',
      reason: null,
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LIVE_POLL_SECONDS * 1000 + 50)
    })

    expect((await screen.findByTestId('player-src')).textContent).toBe(
      '/media/live/public/playlist.m3u8',
    )
    expect(screen.getByText('On air')).toBeTruthy()
    expect(screen.getByText('Council meeting is on air.')).toBeTruthy()
    expect(screen.queryByText('Standing by')).toBeNull()
  })
})
