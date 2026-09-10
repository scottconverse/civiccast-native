// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'
import type { PublicLiveStatus } from '../types'
import { sameLiveStatus } from './homeLive'

// The periodic /current re-resolve dedups steady state (no re-render churn) but
// MUST detect a mid-broadcast source switch — a changed manifest_url is what
// flows to <HlsPlayer> and swaps its source. If sameLiveStatus returned true on
// a manifest_url change, viewers would never follow the surge switch to the CDN.

const base: PublicLiveStatus = {
  state: 'on_air',
  live_session_id: 's1',
  channel_id: 'gov-ch12',
  title: 'Council',
  started_at: '2026-07-08T00:00:00Z',
  manifest_url: 'http://station.local/media/live/gov-ch12/playlist.m3u8',
}

describe('sameLiveStatus', () => {
  it('is true for identical status (dedup: no needless re-render)', () => {
    expect(sameLiveStatus(base, { ...base })).toBe(true)
  })

  it('is false when the manifest_url changes (local -> CDN switch is followed)', () => {
    const switched = { ...base, manifest_url: 'https://cdn.example.org/live/gov-ch12/playlist.m3u8' }
    expect(sameLiveStatus(base, switched)).toBe(false)
  })

  it('is false when the on-air state changes', () => {
    expect(sameLiveStatus(base, { ...base, state: 'offline' })).toBe(false)
  })

  it('is false when there is no prior status yet', () => {
    expect(sameLiveStatus(null, base)).toBe(false)
  })

  it('is false when only the reason changes (the copy depends on it)', () => {
    // Review round 3 delta, MAJOR 3: `on_air_no_web_output` keeps the same
    // state and null manifest whether the web preview is unconfigured or
    // configured-but-not-serving; only `reason` moves, and Home's copy with it.
    const noOutput: PublicLiveStatus = {
      ...base,
      state: 'on_air_no_web_output',
      manifest_url: null,
      reason: 'no HLS output configured',
    }
    const notServing = { ...noOutput, reason: 'HLS output configured but not serving yet' }
    expect(sameLiveStatus(noOutput, { ...noOutput })).toBe(true)
    expect(sameLiveStatus(noOutput, notServing)).toBe(false)
  })
})
