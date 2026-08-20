import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Mock the API client so the container exercises its real query/mutation wiring
// and the role-gate prop without a backend.
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getChannelProgramLog: vi.fn(),
  listCommits: vi.fn(),
  prepareCommit: vi.fn(),
  commitToAir: vi.fn(),
  rollbackCommit: vi.fn(),
}))

import type { ChannelLogEntry, CommitToAirPlan } from '../types/api.generated'
import { getChannelProgramLog, listCommits, prepareCommit } from '../api/client'
import { CommitToAirPanel } from './CommitToAirPanel'

afterEach(cleanup)

const OCC: ChannelLogEntry = {
  occurrence_id: 'occ-1',
  slot_id: 'slot-1',
  channel_id: 'public',
  asset_id: 'city-council',
  title_override: 'City Council',
  occurrence_start: '2026-06-20T18:00:00Z',
  duration_seconds: 1800,
  schedule_item_id: '550e8400-e29b-41d4-a716-446655440000',
  status: 'scheduled',
  detail: '',
}

const PLAN: CommitToAirPlan = {
  plan_id: 'ctap_x',
  channel_id: 'public',
  occurrence_id: 'occ-1',
  schedule_item_id: '550e8400-e29b-41d4-a716-446655440000',
  asset_id: 'city-council',
  title: 'City Council',
  scheduled_at: '2026-06-20T18:00:00Z',
  duration_seconds: 1800,
  dry_run_passed: true,
  conflicts_detected: [],
  gaps_detected: [],
  created_at: '2026-06-15T12:00:00Z',
}

function renderPanel(canManage: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommitToAirPanel channelId="public" canManage={canManage} />
    </QueryClientProvider>,
  )
}

describe('CommitToAirPanel container', () => {
  it('lists upcoming occurrences and disables Review for a non-manager (fail-closed)', async () => {
    vi.mocked(getChannelProgramLog).mockResolvedValue([OCC])
    vi.mocked(listCommits).mockResolvedValue([])
    const { findByText, getByText } = renderPanel(false)
    expect(await findByText('City Council')).toBeTruthy()
    await waitFor(() =>
      expect((getByText('Review & prepare') as HTMLButtonElement).disabled).toBe(true),
    )
    expect(prepareCommit).not.toHaveBeenCalled()
  })

  it('runs the dry-run and reveals the approve action for a manager', async () => {
    vi.mocked(getChannelProgramLog).mockResolvedValue([OCC])
    vi.mocked(listCommits).mockResolvedValue([])
    vi.mocked(prepareCommit).mockResolvedValue(PLAN)
    const { findByText } = renderPanel(true)
    fireEvent.click(await findByText('Review & prepare'))
    expect(await findByText('Approve & put on air')).toBeTruthy()
    expect(prepareCommit).toHaveBeenCalledWith({
      channel_id: 'public',
      occurrence_id: 'occ-1',
      schedule_item_id: '550e8400-e29b-41d4-a716-446655440000',
    })
  })

  it('shows an empty state when nothing is scheduled', async () => {
    vi.mocked(getChannelProgramLog).mockResolvedValue([])
    vi.mocked(listCommits).mockResolvedValue([])
    const { findByText } = renderPanel(true)
    expect(await findByText(/No upcoming programs are scheduled/)).toBeTruthy()
  })
})
