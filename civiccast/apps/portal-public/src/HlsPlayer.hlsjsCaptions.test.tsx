// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Regression coverage for the hls.js/MediaSource caption-selection race
// root-caused on the webkit CI lane (a11y.spec.ts's "caption controls..."
// test): hls.js's SubtitleTrackController polls the video's native
// <track> elements to keep hls.subtitleTrack in sync with the browser's
// own native captions UI. On WebKit (no TextTrackList#onchange) that poll
// can sample before the native <track> DOM element for the
// just-auto-selected default subtitle exists -- creating it requires an
// async fetch of the subtitle sub-playlist -- and, seeing nothing marked
// "showing" yet, force-resets hls.subtitleTrack to -1
// (video-dev/hls.js#1948, #4345). HlsPlayer.tsx now tracks what its own UI
// asked for (desiredSubtitleTrackRef) independently of hls.js's internal
// trackId and reasserts it whenever a SUBTITLE_TRACK_SWITCH disagrees, so
// the fake hls.js below simulates exactly that spurious internal
// correction and asserts the component recovers.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HlsPlayer } from './HlsPlayer'

const Events = {
  MEDIA_ATTACHED: 'hlsMediaAttached',
  MANIFEST_PARSED: 'hlsManifestParsed',
  SUBTITLE_TRACKS_UPDATED: 'hlsSubtitleTracksUpdated',
  SUBTITLE_TRACK_SWITCH: 'hlsSubtitleTrackSwitch',
  ERROR: 'hlsError',
} as const

const ErrorTypes = {
  NETWORK_ERROR: 'networkError',
  OTHER_ERROR: 'otherError',
} as const

interface FakeSubtitleTrack {
  name: string
  lang: string
  default: boolean
}

/**
 * Minimal fake standing in for hls.js's public surface, with two seams a
 * real hls.js instance does not expose: `emitSubtitleTracksUpdated()` lets
 * a test drive the exact "tracks known, but hls.subtitleTrack has not been
 * assigned yet" instant a real SUBTITLE_TRACKS_UPDATED listener observes,
 * and `simulateSpuriousPollReset()` drives hls.js's own internal
 * native-<track>-polling correction directly (bypassing the public
 * `subtitleTrack` setter HlsPlayer itself calls) so the test can assert
 * HlsPlayer fights back against it exactly like the real bug required.
 */
class FakeHls {
  static isSupported() {
    return true
  }
  static Events = Events
  static ErrorTypes = ErrorTypes

  private listeners = new Map<string, Array<(event: string, data: unknown) => void>>()
  private _subtitleTracks: FakeSubtitleTrack[] = []
  private _subtitleTrack = -1
  subtitleDisplay = true

  on(event: string, cb: (event: string, data: unknown) => void) {
    const list = this.listeners.get(event) ?? []
    list.push(cb)
    this.listeners.set(event, list)
  }

  private emit(event: string, data: unknown) {
    for (const cb of this.listeners.get(event) ?? []) cb(event, data)
  }

  attachMedia() {
    this.emit(Events.MEDIA_ATTACHED, {})
  }
  loadSource() {
    this.emit(Events.MANIFEST_PARSED, {})
  }
  destroy() {}

  get subtitleTracks() {
    return this._subtitleTracks
  }
  get subtitleTrack() {
    return this._subtitleTrack
  }
  set subtitleTrack(id: number) {
    this._subtitleTrack = id
    this.emit(Events.SUBTITLE_TRACK_SWITCH, { id })
  }

  /** Simulates hls.js announcing tracks before it has assigned a default. */
  seedTracks(tracks: FakeSubtitleTrack[]) {
    this._subtitleTracks = tracks
    this.emit(Events.SUBTITLE_TRACKS_UPDATED, {})
  }

  /**
   * Simulates the actual upstream bug: hls.js's own native-<track>-polling
   * reconciliation deciding (wrongly, mid-load) that nothing is showing
   * and forcing its internal trackId back to -1, WITHOUT that request
   * coming from HlsPlayer's own `subtitleTrack =` setter.
   */
  simulateSpuriousPollReset() {
    this._subtitleTrack = -1
    this.emit(Events.SUBTITLE_TRACK_SWITCH, { id: -1 })
  }
}

let lastInstance: FakeHls | undefined

vi.mock('hls.js', () => ({
  default: class extends FakeHls {
    constructor() {
      super()
      // Test double needs to hand its own instance back to the test so it
      // can drive seedTracks()/simulateSpuriousPollReset() on the exact
      // instance HlsPlayer constructed.
      // eslint-disable-next-line @typescript-eslint/no-this-alias
      lastInstance = this
    }
  },
}))

afterEach(() => {
  vi.restoreAllMocks()
  lastInstance = undefined
})

describe('HlsPlayer hls.js captions', () => {
  it('derives the default selection from the manifest, not from a stale hls.subtitleTrack read', async () => {
    render(<HlsPlayer manifestUrl="/hlsjs-captioned/playlist.m3u8" />)

    await waitFor(() => expect(lastInstance).toBeDefined())
    const hls = lastInstance as FakeHls

    // Real hls.js fires SUBTITLE_TRACKS_UPDATED before it assigns
    // hls.subtitleTrack for the manifest's DEFAULT=YES track (see
    // subtitle-track-controller.ts's switchLevel: the trigger() call
    // precedes the setSubtitleTrack() call). hls.subtitleTrack is still -1
    // at the exact instant this fires.
    hls.seedTracks([
      { name: 'English', lang: 'en', default: true },
      { name: 'Spanish', lang: 'es', default: false },
    ])

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed')).toBe(
        'true',
      )
    })
    expect(screen.getByRole('button', { name: 'Spanish' }).getAttribute('aria-pressed')).toBe(
      'false',
    )
  })

  it('reasserts the desired track when hls.js spuriously reverts it to -1', async () => {
    render(<HlsPlayer manifestUrl="/hlsjs-captioned/playlist.m3u8" />)

    await waitFor(() => expect(lastInstance).toBeDefined())
    const hls = lastInstance as FakeHls

    hls.seedTracks([
      { name: 'English', lang: 'en', default: true },
      { name: 'Spanish', lang: 'es', default: false },
    ])
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed')).toBe(
        'true',
      )
    })

    // The native-<track>-polling reconciliation misfires (the bug this
    // test exists for) and force-resets hls.js's internal selection.
    // HlsPlayer's SUBTITLE_TRACK_SWITCH handler reasserts synchronously
    // (same call stack, no re-render/tick needed), so by the time this
    // call returns hls.js's internal state is already corrected back --
    // that immediacy is itself part of what the fix buys over the old
    // Playwright-level toPass retry.
    hls.simulateSpuriousPollReset()
    expect(hls.subtitleTrack).toBe(0)

    // ...and the button UI (driven by React state) durably reflects it too.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed')).toBe(
        'true',
      )
    })
    expect(hls.subtitleTrack).toBe(0)
  })

  it('an explicit "Off" click is not overwritten by a later manifest-default reseed', async () => {
    render(<HlsPlayer manifestUrl="/hlsjs-captioned/playlist.m3u8" />)

    await waitFor(() => expect(lastInstance).toBeDefined())
    const hls = lastInstance as FakeHls

    hls.seedTracks([
      { name: 'English', lang: 'en', default: true },
      { name: 'Spanish', lang: 'es', default: false },
    ])
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed')).toBe(
        'true',
      )
    })

    fireEvent.click(screen.getByRole('button', { name: 'Off' }))
    expect(screen.getByRole('button', { name: 'Off' }).getAttribute('aria-pressed')).toBe('true')

    // A second SUBTITLE_TRACKS_UPDATED (e.g. a mid-stream level switch)
    // must not silently re-select the manifest default over the viewer's
    // explicit choice -- this is exactly why "not yet decided" and
    // "explicitly off" are different states internally.
    hls.seedTracks([
      { name: 'English', lang: 'en', default: true },
      { name: 'Spanish', lang: 'es', default: false },
    ])

    expect(screen.getByRole('button', { name: 'Off' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed')).toBe(
      'false',
    )
  })
})
