import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { ImportBatch, ImportPlan, StaffIdentityResponse } from '../types/api.generated'

vi.mock('../api/client', () => ({ getStaffIdentity: vi.fn() }))
vi.mock('../api/stationImport', () => ({
  previewStationImport: vi.fn(),
  applyStationImport: vi.fn(),
  listStationImportBatches: vi.fn(),
  rollbackStationImport: vi.fn(),
}))

import { getStaffIdentity } from '../api/client'
import {
  applyStationImport,
  listStationImportBatches,
  previewStationImport,
  rollbackStationImport,
} from '../api/stationImport'
import { StationImportScreen } from './StationImportScreen'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<MemoryRouter><QueryClientProvider client={client}><StationImportScreen /></QueryClientProvider></MemoryRouter>)
}

const plan: ImportPlan = {
  plan_id: 'preview-1',
  source_system: 'cablecast',
  shows_to_create: [{ source_ref: 'show-42', asset_id: 'asset-42', title: 'Council meeting' }],
  schedule_items_to_create: [{ source_ref: 'slot-42', show_source_ref: 'show-42', asset_id: 'asset-42', channel_id: 'public', scheduled_at: '2026-10-16T10:00:00Z', duration_seconds: 3600 }],
  conflicts: [{ kind: 'show', source_ref: 'show-9', reason: 'A matching show already exists.' }],
  skipped: [{ kind: 'playlist', source_ref: 'playlist-5', reason: 'Playlist import is not supported.' }],
}
const batch: ImportBatch = {
  import_batch_id: 'batch-1', source_system: 'cablecast', status: 'applied',
  shows_created: 1, schedule_items_created: 1, apply_failures: [], created_at: '2026-10-15T12:00:00Z',
}

describe('StationImportScreen', () => {
  it('keeps non-admins out of the import workflow', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue({ roles: ['meeting_operator'] } as StaffIdentityResponse)
    renderScreen()
    expect(await screen.findByText(/requires a setup administrator/)).toBeTruthy()
    expect(previewStationImport).not.toHaveBeenCalled()
  })

  it('previews conflicts before apply, clears the password, and exposes the batch rollback', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue({ roles: ['setup_admin'] } as StaffIdentityResponse)
    vi.mocked(listStationImportBatches).mockResolvedValueOnce([]).mockResolvedValue([batch])
    vi.mocked(previewStationImport).mockResolvedValue(plan)
    vi.mocked(applyStationImport).mockResolvedValue(batch)
    vi.mocked(rollbackStationImport).mockResolvedValue({ ...batch, status: 'rolled_back', rolled_back_at: '2026-10-15T12:05:00Z' })
    renderScreen()

    const url = await screen.findByLabelText('Cablecast API URL')
    fireEvent.change(url, { target: { value: 'https://station.example/cablecastapi/v1' } })
    fireEvent.change(screen.getByLabelText('Username (if required)'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('Password (if required)'), { target: { value: 'private-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview import' }))
    await waitFor(() => expect(previewStationImport).toHaveBeenCalledWith({
      source_system: 'cablecast', base_url: 'https://station.example/cablecastapi/v1',
      username: 'operator', password: 'private-password',
    }, expect.anything()))
    expect(await screen.findByText(/A matching show already exists/)).toBeTruthy()
    expect(screen.getByText(/Playlist import is not supported/)).toBeTruthy()
    expect((screen.getByLabelText('Password (if required)') as HTMLInputElement).value).toBe('')

    const applyButton = screen.getByRole('button', { name: 'Apply this import' }) as HTMLButtonElement
    expect(applyButton.disabled).toBe(true)
    fireEvent.click(screen.getByLabelText(/I reviewed the proposed rows/))
    fireEvent.click(applyButton)
    await waitFor(() => expect(applyStationImport).toHaveBeenCalledWith(plan, expect.anything()))
    expect(await screen.findByText(/Import completed/)).toBeTruthy()
    const rollbackButton = await screen.findByRole('button', { name: 'Roll back this batch' })
    fireEvent.click(rollbackButton)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm rollback' }))
    await waitFor(() => expect(rollbackStationImport).toHaveBeenCalledWith('batch-1', expect.anything()))
    expect(await screen.findByText(/Import rolled back/)).toBeTruthy()
  })
})
