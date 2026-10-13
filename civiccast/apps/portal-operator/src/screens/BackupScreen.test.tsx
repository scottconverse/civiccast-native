// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/backups', () => ({
  createStationBackup: vi.fn(),
  downloadStationBackup: vi.fn(),
  getStationBackupStatus: vi.fn(),
  setScheduledBackupPassphrase: vi.fn(),
  updateStationBackupSchedule: vi.fn(),
  verifyStationBackup: vi.fn(),
}))

import {
  createStationBackup,
  getStationBackupStatus,
} from '../api/backups'
import { BackupScreen } from './BackupScreen'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <BackupScreen />
    </QueryClientProvider>,
  )
}

describe('BackupScreen', () => {
  it('shows an empty state and creates only after matching recovery passphrases', async () => {
    vi.mocked(getStationBackupStatus).mockResolvedValue({
      schedule: {
        enabled: false,
        destination: 'D:\\CivicCastBackups',
        hour_utc: 3,
        minute_utc: 0,
        retention_count: 14,
        selected_media_roots: [],
      },
      scheduled_passphrase_configured: false,
      job: { phase: 'idle', percent: 0 },
      last_success: null,
      last_error: null,
      backups: [],
    })
    vi.mocked(createStationBackup).mockResolvedValue({
      backup_id: 'station-backup-20261013T120000Z-0123abcd',
      file_name: 'station-backup-20261013T120000Z-0123abcd.ccbackup',
      created_at: '2026-10-13T12:00:00Z',
      size_bytes: 1024,
    })

    renderScreen()
    expect(await screen.findByText(/No station backups are available yet/)).toBeTruthy()
    const create = screen.getByRole('button', { name: 'Create backup' })
    expect((create as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText('Recovery passphrase'), {
      target: { value: 'a-long-recovery-passphrase' },
    })
    fireEvent.change(screen.getByLabelText('Confirm passphrase'), {
      target: { value: 'a-different-recovery-passphrase' },
    })
    expect((create as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Confirm passphrase'), {
      target: { value: 'a-long-recovery-passphrase' },
    })
    fireEvent.click(create)

    await waitFor(() => expect(createStationBackup).toHaveBeenCalled())
    expect(vi.mocked(createStationBackup).mock.calls[0]?.[0]).toBe('a-long-recovery-passphrase')
    expect(await screen.findByText(/Encrypted backup created/)).toBeTruthy()
  })
})
