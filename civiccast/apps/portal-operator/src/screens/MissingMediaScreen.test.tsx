import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  listMissingMedia: vi.fn(),
}))

import { listMissingMedia } from '../api/client'
import { MissingMediaScreen } from './MissingMediaScreen'

afterEach(cleanup)

function renderScreen(onOpenAsset = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MissingMediaScreen onOpenAsset={onOpenAsset} />
      </QueryClientProvider>,
    ),
    onOpenAsset,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MissingMediaScreen', () => {
  it('shows the empty state when nothing is missing', async () => {
    vi.mocked(listMissingMedia).mockResolvedValue([])
    const { findByText } = renderScreen()
    expect(await findByText('Nothing missing.')).toBeTruthy()
  })

  it('shows an error state and can retry', async () => {
    vi.mocked(listMissingMedia).mockRejectedValueOnce(new Error('network down'))
    const { findByRole } = renderScreen()
    expect(await findByRole('alert')).toBeTruthy()

    vi.mocked(listMissingMedia).mockResolvedValueOnce([])
    fireEvent.click(await findByRole('button', { name: 'Retry' }))
  })

  it('lists a missing-media alert and opens the asset on click', async () => {
    vi.mocked(listMissingMedia).mockResolvedValue([
      {
        schedule_id: 'sched-1',
        asset_id: 'asset-1',
        asset_title: 'City Council 2026-06-15',
        channel_id: 'public',
        scheduled_start: '2026-06-15T13:00:00Z',
        asset_state: 'pending_ingest',
        reason: "Asset is in state 'pending_ingest', not validated/recorded.",
      },
    ])
    const { findByText, findByRole, onOpenAsset } = renderScreen()

    expect(await findByText(/City Council 2026-06-15/)).toBeTruthy()
    expect(await findByText(/not validated\/recorded/)).toBeTruthy()

    fireEvent.click(await findByRole('button', { name: 'Open asset' }))
    expect(onOpenAsset).toHaveBeenCalledWith('asset-1')
  })
})
