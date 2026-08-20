// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HlsPlayer } from './HlsPlayer'

vi.mock('hls.js', () => ({
  default: class UnsupportedHls {
    static isSupported() {
      return false
    }
  },
}))

type MutableTextTrack = {
  label: string
  language: string
  mode: TextTrackMode
}

function nativeTextTracks(...tracks: MutableTextTrack[]): TextTrackList {
  const list = new EventTarget() as TextTrackList & Record<number, MutableTextTrack>
  Object.defineProperty(list, 'length', { value: tracks.length })
  tracks.forEach((track, index) => {
    list[index] = track as TextTrack & MutableTextTrack
  })
  return list
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('HlsPlayer native-HLS captions', () => {
  it('renders and operates CivicCast caption controls from native text tracks', async () => {
    const english: MutableTextTrack = {
      label: 'English',
      language: 'en',
      mode: 'showing',
    }
    const spanish: MutableTextTrack = {
      label: 'Spanish',
      language: 'es',
      mode: 'disabled',
    }
    const tracks = nativeTextTracks(english, spanish)

    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('maybe')
    vi.spyOn(HTMLMediaElement.prototype, 'textTracks', 'get').mockReturnValue(tracks)

    render(<HlsPlayer manifestUrl="/native-captioned/playlist.m3u8" />)
    const video = screen.getByLabelText('Meeting video player')
    fireEvent.loadedMetadata(video)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'English' }).getAttribute('aria-pressed'),
      ).toBe('true')
    })

    fireEvent.click(screen.getByRole('button', { name: 'Spanish' }))
    expect(english.mode).toBe('disabled')
    expect(spanish.mode).toBe('showing')
    expect(
      screen.getByRole('button', { name: 'Spanish' }).getAttribute('aria-pressed'),
    ).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'Off' }))
    expect(english.mode).toBe('disabled')
    expect(spanish.mode).toBe('disabled')
    expect(
      screen.getByRole('button', { name: 'Off' }).getAttribute('aria-pressed'),
    ).toBe('true')
  })
})
