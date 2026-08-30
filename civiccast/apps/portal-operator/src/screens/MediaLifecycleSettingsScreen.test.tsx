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
  scanWatchFolderNow: vi.fn(),
  browseFolders: vi.fn(),
  listRetentionPolicies: vi.fn(),
  createRetentionPolicy: vi.fn(),
  deleteRetentionPolicy: vi.fn(),
  applyRetentionPolicies: vi.fn(),
  getStorageBudget: vi.fn(),
}))

import {
  ApiError,
  browseFolders,
  createWatchFolderConfig,
  getStorageBudget,
  listRetentionPolicies,
  listWatchFolderConfigs,
  scanWatchFolderNow,
} from '../api/client'
import type { WatchFolderConfigResponse } from '../types/api.generated'
import { MediaLifecycleSettingsScreen } from './MediaLifecycleSettingsScreen'

afterEach(cleanup)

// S7 watch-folder daemon: health_status/last_poll_at/last_ingest_at/
// degraded_reason are worker-owned fields the settings screen now renders
// (WatchFolderStatus). Defaults here match a freshly-created, never-polled
// config; individual tests override what they need.
function watchFolderConfigFixture(
  overrides: Partial<WatchFolderConfigResponse> = {},
): WatchFolderConfigResponse {
  return {
    config_id: 'wf-1',
    monitor_path: '/mnt/nas/incoming',
    import_naming_pattern: null,
    enabled: true,
    settle_window_seconds: 10,
    retention_policy_default: null,
    last_scanned_at: null,
    last_scan_files_found: 0,
    poll_interval_seconds: 5,
    processed_file_mode: 'leave_with_ledger',
    processed_subfolder_name: 'processed',
    health_status: 'unknown',
    degraded_reason: null,
    degraded_since: null,
    last_poll_at: null,
    last_ingest_at: null,
    created_at: '2026-08-21T00:00:00Z',
    updated_at: '2026-08-21T00:00:00Z',
    ...overrides,
  }
}

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
    vi.mocked(listWatchFolderConfigs).mockResolvedValue([watchFolderConfigFixture()])
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
    vi.mocked(createWatchFolderConfig).mockResolvedValue(
      watchFolderConfigFixture({ config_id: 'wf-2', monitor_path: '/mnt/usb' }),
    )
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

  it('shows "not scanned yet" status with a friendly explanation for a fresh config, not a bare "never"', async () => {
    // Candidate #17 tester finding 4: "Last poll: never" with no other
    // feedback read as broken, even though the daemon HAD auto-ingested
    // within about a minute. The fresh-config state must say something an
    // operator can act on (when the next automatic check runs, and that
    // Scan now exists) instead of a bare "never."
    vi.mocked(listWatchFolderConfigs).mockResolvedValue([
      watchFolderConfigFixture({ poll_interval_seconds: 5 }),
    ])
    const { findByText, queryByText } = renderScreen()

    expect(await findByText('Not scanned yet')).toBeTruthy()
    expect(
      await findByText(
        'No automatic check has run yet — the next one runs within 5s, or use Scan now.',
      ),
    ).toBeTruthy()
    expect(queryByText('Last poll: never')).toBeNull()
  })

  it('shows a healthy status with relative last-poll/ingest times once the daemon has run', async () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString()
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString()
    vi.mocked(listWatchFolderConfigs).mockResolvedValue([
      watchFolderConfigFixture({
        health_status: 'ok',
        last_poll_at: fiveMinutesAgo,
        last_ingest_at: oneHourAgo,
      }),
    ])
    const { findByText } = renderScreen()

    expect(await findByText('OK')).toBeTruthy()
    expect(await findByText('Last poll: 5m ago')).toBeTruthy()
    expect(await findByText('Last ingest: 1h ago')).toBeTruthy()
  })

  it('surfaces a degraded watch folder with its reason, visibly, not silently', async () => {
    vi.mocked(listWatchFolderConfigs).mockResolvedValue([
      watchFolderConfigFixture({
        monitor_path: '\\\\nas\\incoming',
        health_status: 'degraded',
        degraded_reason: '[WinError 53] The network path was not found',
        degraded_since: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
        last_poll_at: new Date(Date.now() - 30 * 1000).toISOString(),
      }),
    ])
    const { findByText, findByRole } = renderScreen()

    const degraded = await findByText('Degraded')
    expect(degraded).toBeTruthy()
    // Degraded is an alert, not decorative text -- screen readers must
    // announce it, matching this app's WCAG 2.2 AA / accessibility bar.
    const alertEl = await findByRole('alert')
    expect(alertEl.textContent).toContain('Degraded')
    expect(await findByText('[WinError 53] The network path was not found')).toBeTruthy()
  })

  describe('Scan now (candidate #17 finding 4)', () => {
    it('scans a folder on demand and reports what it found', async () => {
      const config = watchFolderConfigFixture()
      vi.mocked(listWatchFolderConfigs).mockResolvedValue([config])
      vi.mocked(scanWatchFolderNow).mockResolvedValue({
        config: { ...config, health_status: 'ok', last_poll_at: new Date().toISOString() },
        healthy: true,
        files_seen: 2,
        files_ingested: 1,
        files_reprocessed: 0,
        files_failed: 0,
        error: null,
      })
      const { findByRole, push } = renderScreen()

      fireEvent.click(await findByRole('button', { name: 'Scan now' }))

      await waitFor(() => expect(scanWatchFolderNow).toHaveBeenCalledWith('wf-1'))
      await waitFor(() =>
        expect(push).toHaveBeenCalledWith(
          expect.objectContaining({ tone: 'success', message: expect.stringContaining('1 file(s) ingested') }),
        ),
      )
    })

    it('reports an empty scan without claiming anything is broken', async () => {
      const config = watchFolderConfigFixture()
      vi.mocked(listWatchFolderConfigs).mockResolvedValue([config])
      vi.mocked(scanWatchFolderNow).mockResolvedValue({
        config,
        healthy: true,
        files_seen: 0,
        files_ingested: 0,
        files_reprocessed: 0,
        files_failed: 0,
        error: null,
      })
      const { findByRole, push } = renderScreen()

      fireEvent.click(await findByRole('button', { name: 'Scan now' }))

      await waitFor(() =>
        expect(push).toHaveBeenCalledWith(
          expect.objectContaining({ tone: 'info', message: expect.stringContaining('no files found') }),
        ),
      )
    })

    it('shows a plain-language error inline when the scan request itself fails', async () => {
      const config = watchFolderConfigFixture()
      vi.mocked(listWatchFolderConfigs).mockResolvedValue([config])
      vi.mocked(scanWatchFolderNow).mockRejectedValue(
        new ApiError(
          'Request failed: 503',
          503,
          'The watch-folder daemon is not running in this deployment.',
        ),
      )
      const { findByRole, findByText } = renderScreen()

      fireEvent.click(await findByRole('button', { name: 'Scan now' }))

      expect(
        await findByText('The watch-folder daemon is not running in this deployment.'),
      ).toBeTruthy()
    })
  })

  describe('Folder browser (candidate #17 finding 3)', () => {
    it('opens the browser, navigates into a folder, and fills the path on selection', async () => {
      vi.mocked(browseFolders).mockImplementation((path) =>
        Promise.resolve(
          path
            ? {
                current_path: path,
                parent_path: null,
                separator: '\\',
                entries: [],
                readable: true,
              }
            : {
                current_path: null,
                parent_path: null,
                separator: '\\',
                entries: [{ name: 'D:\\', path: 'D:\\' }],
                readable: true,
              },
        ),
      )
      const { findByRole, findByLabelText } = renderScreen()

      fireEvent.click(await findByRole('button', { name: 'Browse…' }))
      fireEvent.click(await findByRole('button', { name: /D:\\/ }))
      fireEvent.click(await findByRole('button', { name: 'Use this folder' }))

      const input = await findByLabelText('Watch folder path')
      await waitFor(() => expect((input as HTMLInputElement).value).toBe('D:\\'))
    })

    it('shows an unreadable-folder message instead of a blank list', async () => {
      vi.mocked(browseFolders).mockResolvedValue({
        current_path: null,
        parent_path: null,
        separator: '\\',
        entries: [],
        readable: false,
        error: 'Permission denied',
      })
      const { findByRole, findByText } = renderScreen()

      fireEvent.click(await findByRole('button', { name: 'Browse…' }))

      expect(await findByText(/Permission denied/)).toBeTruthy()
    })
  })
})
