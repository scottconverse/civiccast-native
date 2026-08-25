import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ToastContext } from '../components/toast-context'

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
  listWatchFolderConfigs: vi.fn(),
  createWatchFolderConfig: vi.fn(),
  deleteWatchFolderConfig: vi.fn(),
  listRetentionPolicies: vi.fn(),
  createRetentionPolicy: vi.fn(),
  deleteRetentionPolicy: vi.fn(),
  applyRetentionPolicies: vi.fn(),
  getStorageBudget: vi.fn(),
}))

import {
  createWatchFolderConfig,
  getStorageBudget,
  listRetentionPolicies,
  listWatchFolderConfigs,
} from '../api/client'
import { MediaLifecycleSettingsScreen } from './MediaLifecycleSettingsScreen'

afterEach(cleanup)

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const push = vi.fn()
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ToastContext.Provider value={{ push }}>
          <MediaLifecycleSettingsScreen />
        </ToastContext.Provider>
      </QueryClientProvider>,
    ),
    push,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listWatchFolderConfigs).mockResolvedValue([])
  vi.mocked(listRetentionPolicies).mockResolvedValue([])
  vi.mocked(getStorageBudget).mockResolvedValue({
    total_bytes_used: 0,
    budget_bytes: null,
    percent_used: null,
    by_retention_policy: [],
  })
})

describe('MediaLifecycleSettingsScreen', () => {
  it('shows empty states for all three sections when nothing is configured', async () => {
    const { findByText } = renderScreen()
    expect(await findByText(/No watch folders configured yet/)).toBeTruthy()
    expect(await findByText(/No automation rules yet/)).toBeTruthy()
    expect(await findByText(/No budget configured/)).toBeTruthy()
  })

  it('lists existing watch folders and storage totals', async () => {
    vi.mocked(listWatchFolderConfigs).mockResolvedValue([
      {
        config_id: 'wf-1',
        monitor_path: '/mnt/nas/incoming',
        import_naming_pattern: null,
        enabled: true,
        settle_window_seconds: 10,
        retention_policy_default: null,
        last_scanned_at: null,
        last_scan_files_found: 0,
        created_at: '2026-08-21T00:00:00Z',
        updated_at: '2026-08-21T00:00:00Z',
      },
    ])
    vi.mocked(getStorageBudget).mockResolvedValue({
      total_bytes_used: 1_500_000,
      budget_bytes: 10_000_000,
      percent_used: 15,
      by_retention_policy: [{ retention_policy: 'default', asset_count: 2, bytes_used: 1_500_000 }],
    })
    const { findByText, findAllByText } = renderScreen()

    expect(await findByText('/mnt/nas/incoming')).toBeTruthy()
    const totals = await findAllByText(/1\.4 MB/)
    expect(totals.length).toBeGreaterThanOrEqual(1)
  })

  it('adds a watch folder through the form', async () => {
    vi.mocked(createWatchFolderConfig).mockResolvedValue({
      config_id: 'wf-2',
      monitor_path: '/mnt/usb',
      import_naming_pattern: null,
      enabled: true,
      settle_window_seconds: 10,
      retention_policy_default: null,
      last_scanned_at: null,
      last_scan_files_found: 0,
      created_at: '2026-08-21T00:00:00Z',
      updated_at: '2026-08-21T00:00:00Z',
    })
    const { findByRole, findByLabelText } = renderScreen()

    const input = await findByLabelText('Watch folder path')
    fireEvent.change(input, { target: { value: '/mnt/usb' } })
    fireEvent.click(await findByRole('button', { name: 'Add watch folder' }))

    await waitFor(() =>
      expect(createWatchFolderConfig).toHaveBeenCalledWith({
        monitor_path: '/mnt/usb',
        settle_window_seconds: 10,
        enabled: true,
      }),
    )
  })
})
