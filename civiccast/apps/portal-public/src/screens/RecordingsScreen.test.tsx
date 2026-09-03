// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Finding MAJOR-3 (2026-09-03 UI walkthrough): /api/public/search 503s under
// ephemeral/dev storage (no durable search index) while /api/public/assets
// -- the simpler packaged-asset list -- still has the data. These tests pin
// the fallback: a 503 from search degrades to the assets list with a visible
// note, rather than hard-failing the whole screen; any other search failure
// (network error, 500) still shows the plain error state.
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RecordingsScreen } from './RecordingsScreen'

const ASSET = {
  asset_id: 'council-2026-05-08',
  title: 'Council - May 8, 2026',
  description: 'Regular council meeting',
  meeting_body: null,
  manifest_url: '/media/vod/council-2026-05-08/playlist.m3u8',
  poster_url: null,
  duration_seconds: 3600,
  published_at: '2026-05-08T20:00:00Z',
}

function baseProps() {
  return { query: '', year: '', body: '', cf: {}, page: 1 }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RecordingsScreen search fallback', () => {
  it('falls back to /api/public/assets with a visible note when search 503s', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/public/search')) {
        return new Response(JSON.stringify({ detail: 'Durable storage is not ready yet.' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.startsWith('/api/public/assets')) {
        return new Response(JSON.stringify([ASSET]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as unknown as typeof fetch

    render(<RecordingsScreen {...baseProps()} />)

    expect(await screen.findByText('Council - May 8, 2026')).toBeTruthy()
    expect(
      screen.getByText(/reduced-search mode — full search is temporarily unavailable/),
    ).toBeTruthy()
  })

  it('shows the plain error state when both search and the assets fallback fail', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/public/search')) {
        return new Response(JSON.stringify({ detail: 'Durable storage is not ready yet.' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.startsWith('/api/public/assets')) {
        return new Response(JSON.stringify({ detail: 'Durable storage is not ready yet.' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as unknown as typeof fetch

    render(<RecordingsScreen {...baseProps()} />)

    expect(
      await screen.findByText('Published recordings could not be loaded. Try again or contact the station.'),
    ).toBeTruthy()
  })

  it('shows the plain error state on a non-503 search failure without trying the fallback', async () => {
    const assetsCalls: string[] = []
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.startsWith('/api/public/search')) {
        return new Response(JSON.stringify({ detail: 'Internal error' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.startsWith('/api/public/assets')) {
        assetsCalls.push(url)
        return new Response(JSON.stringify([ASSET]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as unknown as typeof fetch

    render(<RecordingsScreen {...baseProps()} />)

    expect(
      await screen.findByText('Published recordings could not be loaded. Try again or contact the station.'),
    ).toBeTruthy()
    expect(assetsCalls).toEqual([])
  })
})
