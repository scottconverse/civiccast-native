// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'

// beta.5 clean-machine walkthrough: the channel was on air (slate, then a
// scheduled asset) on a UDP headend preset, and the resident Home said
// "Offline" the whole time. /api/public/live/current now reports
// `on_air_no_web_output` for that case; Home must say so in plain words, and
// must still say "Offline" only when the API says offline.

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

beforeEach(() => {
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
    return json({}) // idle page, submission agreement, emergency overlay, etc.
  }) as unknown as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('HomeScreen when the channel is on air without an HLS web output', () => {
  it('says "on air, web preview not enabled" instead of "Offline"', async () => {
    liveBody = {
      state: 'on_air_no_web_output',
      live_session_id: null,
      channel_id: 'public',
      title: 'Council meeting',
      started_at: '2026-09-08T18:00:00+00:00',
      manifest_url: null,
      reason: 'no HLS output configured',
    }
    render(<HomeScreen />)

    expect(
      await screen.findByText('Council meeting is on air, but web preview is not enabled for this channel.'),
    ).toBeTruthy()
    // Broadcast status row: on air, qualified — never the word Offline.
    expect(screen.getByText('On air (no web preview)')).toBeTruthy()
    expect(screen.queryByText('Offline')).toBeNull()
    // The player slot explains itself instead of the generic "appears here" copy.
    expect(screen.getByRole('status').textContent).toContain(
      'On air, but web preview is not enabled for this channel.',
    )
    expect(screen.queryByText('Live video appears here when the station goes on air.')).toBeNull()
    expect(screen.queryByTestId('player-src')).toBeNull()
  })

  it('still says Offline when the API says offline', async () => {
    liveBody = {
      state: 'offline',
      live_session_id: null,
      channel_id: null,
      title: null,
      started_at: null,
      manifest_url: null,
      reason: null,
    }
    render(<HomeScreen />)

    expect(await screen.findByText('No live broadcast is on air.')).toBeTruthy()
    expect(screen.getByText('Offline')).toBeTruthy()
    expect(screen.queryByText(/web preview is not enabled/)).toBeNull()
  })

  it('plays the manifest and says On air when the egress path resolves an HLS URL', async () => {
    liveBody = {
      state: 'on_air',
      live_session_id: null,
      channel_id: 'public',
      title: 'Slate',
      started_at: '2026-09-08T18:00:00+00:00',
      manifest_url: 'http://127.0.0.1:8000/media/live/public/playlist.m3u8',
      reason: null,
    }
    render(<HomeScreen />)

    expect((await screen.findByTestId('player-src')).textContent).toBe(
      'http://127.0.0.1:8000/media/live/public/playlist.m3u8',
    )
    expect(screen.getByText('Slate is on air.')).toBeTruthy()
    expect(screen.getByText('On air')).toBeTruthy()
  })
})
