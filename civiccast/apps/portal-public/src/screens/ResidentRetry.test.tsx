// SPDX-License-Identifier: Apache-2.0
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchJson } from '../api'
import { ChannelGuideScreen } from './ChannelGuideScreen'
import { RecordingsScreen } from './RecordingsScreen'
import { WatchScreen } from './WatchScreen'

vi.mock('../api', () => ({
  fetchJson: vi.fn(),
  formatDateTime: (value: string) => value,
  formatDuration: (value: number) => String(value),
}))

vi.mock('../HlsPlayer', () => ({
  HlsPlayer: () => <div data-testid="player" />,
}))

vi.mock('../PaywallGate', () => ({
  PaywallGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('../MeetingAgendaSidebar', () => ({
  MeetingAgendaSidebar: () => null,
}))

const mockedFetchJson = vi.mocked(fetchJson)

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

beforeEach(() => {
  mockedFetchJson.mockReset()
})

describe('resident error recovery', () => {
  it('retries the recordings request without losing the active filters', async () => {
    const recordings = Array.from({ length: 13 }, (_, index) => ({
      asset_id: `asset-${index + 1}`,
      title: `Budget meeting ${index + 1}`,
      description: 'Parks budget',
      meeting_body: 'Council',
      manifest_url: `/media/${index + 1}.m3u8`,
      poster_url: null,
      duration_seconds: 60,
      published_at: '2026-02-01T12:00:00Z',
      custom_fields: [{ key: 'topic', label: 'Topic', value: 'parks' }],
    }))
    const retry = deferred<typeof recordings>()
    mockedFetchJson.mockRejectedValueOnce(new Error('offline')).mockReturnValueOnce(retry.promise)

    render(<RecordingsScreen query="budget" year="2026" body="Council" cf={{ topic: 'parks' }} page={2} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(screen.getByRole('status').textContent).toContain('Loading published recordings.')
    retry.resolve(recordings)
    expect(await screen.findByText('Budget meeting 13')).toBeTruthy()
    expect((screen.getByRole('searchbox') as HTMLInputElement).value).toBe('budget')
    expect((screen.getByLabelText('Year') as HTMLSelectElement).value).toBe('2026')
    expect((screen.getByLabelText('Meeting body') as HTMLSelectElement).value).toBe('Council')
    expect((screen.getByLabelText('Topic') as HTMLSelectElement).value).toBe('parks')
    expect(mockedFetchJson).toHaveBeenNthCalledWith(2, '/api/public/search')
  })

  it('keeps Retry available after another failed attempt', async () => {
    mockedFetchJson.mockRejectedValue(new Error('still offline'))

    render(<RecordingsScreen query="" year="" body="" cf={{}} page={1} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeTruthy()
    expect(mockedFetchJson).toHaveBeenCalledTimes(2)
  })

  it('retries the same channel guide request', async () => {
    let guideAttempts = 0
    const recoveredGuide = [
      {
        channel_id: 'gov',
        title: 'Recovered council meeting',
        starts_at: '2026-07-14T18:00:00Z',
        duration_seconds: 3600,
      },
    ]
    const retry = deferred<typeof recoveredGuide>()
    mockedFetchJson.mockImplementation((url) => {
      if (String(url).includes('/app/config')) {
        return Promise.resolve({ channels: [{ channel_id: 'gov', branding: {} }] })
      }
      guideAttempts += 1
      if (guideAttempts === 1) return Promise.reject(new Error('offline'))
      return retry.promise
    })

    render(<ChannelGuideScreen channel="gov" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(screen.getByRole('status').textContent).toContain('Loading the channel schedule.')
    retry.resolve(recoveredGuide)
    expect(await screen.findByText('Recovered council meeting')).toBeTruthy()
    expect(mockedFetchJson).toHaveBeenCalledWith(
      '/api/public/programlog/channels/gov/guide?hours=72',
    )
    expect(guideAttempts).toBe(2)
  })

  it('retries the same recording detail request', async () => {
    const recoveredAsset = {
      asset_id: 'meeting/42',
      title: 'Recovered recording',
      description: null,
      meeting_body: 'Council',
      manifest_url: '/media/meeting-42.m3u8',
      poster_url: null,
      duration_seconds: 90,
      published_at: '2026-07-13T12:00:00Z',
    }
    const retry = deferred<typeof recoveredAsset>()
    mockedFetchJson.mockRejectedValueOnce(new Error('offline')).mockReturnValueOnce(retry.promise)

    render(<WatchScreen assetId="meeting/42" />)

    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(screen.getByRole('status').textContent).toContain('Loading this recording.')
    retry.resolve(recoveredAsset)
    expect(await screen.findByRole('heading', { name: 'Recovered recording' })).toBeTruthy()
    expect(mockedFetchJson).toHaveBeenNthCalledWith(2, '/api/public/assets/meeting%2F42')
  })
})
