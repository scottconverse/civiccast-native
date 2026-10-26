// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fetchJson, FetchError } from '../api'
import { WatchScreen } from './WatchScreen'

vi.mock('../api', async (original) => ({
  ...await original<typeof import('../api')>(), fetchJson: vi.fn(),
}))
vi.mock('hls.js', () => ({ default: class { static isSupported() { return false } } }))
vi.mock('../PaywallGate', () => ({ PaywallGate: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('../MeetingAgendaSidebar', () => ({ MeetingAgendaSidebar: () => null }))

beforeEach(() => {
  const tracks = new EventTarget()
  Object.defineProperty(tracks, 'length', { value: 0 })
  vi.spyOn(HTMLMediaElement.prototype, 'textTracks', 'get').mockReturnValue(tracks as TextTrackList)
  vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('maybe')
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.mocked(fetchJson).mockImplementation(async (url) => {
    const path = String(url)
    if (path.endsWith('/transcript')) return { available: true, cues: [{
      cue_id: 'matched', start_seconds: 28, end_seconds: 33.58, text: 'Approved garden project',
    }] }
    const id = path.split('/').pop()!
    return { asset_id: id, title: `Recording ${id}`, manifest_url: `/${id}.m3u8`,
      duration_seconds: 90, published_at: '2026-10-25T12:00:00Z' }
  })
})
afterEach(() => { vi.restoreAllMocks(); vi.mocked(fetchJson).mockReset() })

it('navigates from loaded A to timestamped B and seeks B after its metadata', async () => {
  const { rerender } = render(<WatchScreen assetId="a" />)
  await screen.findByRole('heading', { name: 'Recording a' })
  const oldVideo = screen.getByLabelText('Meeting video player') as HTMLVideoElement
  Object.defineProperty(oldVideo, 'readyState', { value: 1 })
  Object.defineProperty(oldVideo, 'duration', { value: 90 })
  oldVideo.currentTime = 10
  fireEvent.loadedMetadata(oldVideo)
  rerender(<WatchScreen assetId="b" startSeconds={28} />)
  await screen.findByRole('heading', { name: 'Recording b' })
  const newVideo = screen.getByLabelText('Meeting video player') as HTMLVideoElement
  expect(newVideo).not.toBe(oldVideo)
  expect(oldVideo.currentTime).toBe(10)
  Object.defineProperty(newVideo, 'readyState', { value: 1 })
  Object.defineProperty(newVideo, 'duration', { value: 90 })
  fireEvent.loadedMetadata(newVideo)
  expect(newVideo.currentTime).toBe(28)
  const passage = await screen.findByRole('link', { name: /Approved garden project/ })
  expect(passage.getAttribute('href')).toBe('#/watch/b?t=28')
  newVideo.currentTime = 0
  fireEvent.click(passage)
  expect(newVideo.currentTime).toBe(28)
})

it('does not keep transcript text after access is denied on refresh', async () => {
  render(<WatchScreen assetId="a" />)
  await screen.findByRole('link', { name: /Approved garden project/ })
  vi.mocked(fetchJson).mockRejectedValue(new FetchError('Access denied', 403))
  fireEvent.click(screen.getByRole('button', { name: /Refresh transcript/i }))
  await waitFor(() => expect(screen.queryByText('Approved garden project')).toBeNull())
  expect(await screen.findByText(/Sign in again/i)).toBeTruthy()
})

it('keeps the recording player available when no transcript is published', async () => {
  vi.mocked(fetchJson).mockImplementation(async (url) => String(url).endsWith('/transcript')
    ? { available: false, cues: [] }
    : { asset_id: 'a', title: 'Recording a', manifest_url: '/a.m3u8', duration_seconds: 90,
      published_at: '2026-10-25T12:00:00Z' })
  render(<WatchScreen assetId="a" />)
  expect(await screen.findByText('Transcript not available for this recording.')).toBeTruthy()
  expect(screen.getByLabelText('Meeting video player')).toBeTruthy()
  expect(screen.queryByRole('list', { name: 'Recording transcript' })).toBeNull()
})
