// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  EpgExportConfig,
  EpgGenerateResult,
  StaffIdentityResponse,
} from '../types/api.generated'

afterEach(cleanup)

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
  getStaffIdentity: vi.fn(),
  listEpgConfigs: vi.fn(),
  createEpgConfig: vi.fn(),
  patchEpgConfig: vi.fn(),
  deleteEpgConfig: vi.fn(),
  generateEpgExport: vi.fn(),
}))

import {
  createEpgConfig,
  deleteEpgConfig,
  generateEpgExport,
  getStaffIdentity,
  listEpgConfigs,
  patchEpgConfig,
} from '../api/client'
import { EpgExportScreen } from './EpgExportScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'pat', operator_display_name: 'Pat', roles } as StaffIdentityResponse
}

function cfg(overrides: Partial<EpgExportConfig> = {}): EpgExportConfig {
  return {
    config_id: 'epg-tv-guide',
    station_id: 'civiccast-station',
    channel_id: 'pub-1',
    format: 'xlist',
    horizon_days: 14,
    endpoint: null,
    field_map: { channel: 'pub-1' },
    ...overrides,
  }
}

function generateOk(overrides: Partial<EpgGenerateResult> = {}): EpgGenerateResult {
  return {
    format: 'xlist',
    slot_count: 42,
    bytes: 2048,
    document: 'X-LIST...',
    pushed_to: null,
    pushed_at: null,
    error: null,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <EpgExportScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
  vi.mocked(listEpgConfigs).mockResolvedValue([])
  vi.mocked(createEpgConfig).mockImplementation(async (p) => cfg({ ...p }))
  vi.mocked(patchEpgConfig).mockImplementation(async (id, patch) =>
    cfg({ config_id: id, ...(patch as Partial<EpgExportConfig>) }),
  )
  vi.mocked(deleteEpgConfig).mockResolvedValue(undefined)
  vi.mocked(generateEpgExport).mockResolvedValue(generateOk())
  // UX-6: jsdom doesn't implement URL.createObjectURL; mock it so the inline
  // download path can exercise the Blob → object-URL code without crashing.
  if (typeof URL.createObjectURL !== 'function') {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(() => 'blob:mock'),
    })
  } else {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
  }
  if (typeof URL.revokeObjectURL !== 'function') {
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    })
  } else {
    URL.revokeObjectURL = vi.fn()
  }
})

describe('EpgExportScreen access', () => {
  it('shows an access banner for a support_admin (no setup/publish role) and does NOT fetch configs', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin or publish operator role/i)).toBeTruthy()
    expect(vi.mocked(listEpgConfigs)).not.toHaveBeenCalled()
  })

  it('renders for a setup_admin', async () => {
    const { findByRole } = renderScreen()
    expect(await findByRole('button', { name: /create config/i })).toBeTruthy()
  })

  it('renders for a publish_operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByRole } = renderScreen()
    expect(await findByRole('button', { name: /create config/i })).toBeTruthy()
  })
})

describe('EpgExportScreen list + create', () => {
  it('lists existing configs', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg()])
    const { findByText } = renderScreen()
    expect(await findByText('epg-tv-guide')).toBeTruthy()
  })

  it('submits a create with the typed payload', async () => {
    const { findByLabelText, getByRole } = renderScreen()
    fireEvent.change(await findByLabelText('Config ID'), { target: { value: 'epg-titan-tv' } })
    fireEvent.change(await findByLabelText('Channel ID'), { target: { value: 'pub-2' } })
    fireEvent.change(await findByLabelText('Format'), { target: { value: 'xmltv' } })
    fireEvent.change(await findByLabelText('Horizon days'), { target: { value: '7' } })
    fireEvent.change(await findByLabelText('Field map'), {
      target: { value: 'channel=pub-2\ngenre=category' },
    })
    fireEvent.click(getByRole('button', { name: /create config/i }))
    await waitFor(() => expect(vi.mocked(createEpgConfig)).toHaveBeenCalled())
    const payload = vi.mocked(createEpgConfig).mock.calls[0][0]
    expect(payload).toEqual(
      expect.objectContaining({
        config_id: 'epg-titan-tv',
        channel_id: 'pub-2',
        format: 'xmltv',
        horizon_days: 7,
        endpoint: null,
        field_map: { channel: 'pub-2', genre: 'category' },
      }),
    )
  })
})

describe('EpgExportScreen generate', () => {
  it('calls generate for the right config and renders slot_count + bytes', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg()])
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /generate epg-tv-guide/i }))
    await waitFor(() => expect(vi.mocked(generateEpgExport)).toHaveBeenCalledWith('epg-tv-guide'))
    // "42" is in a <strong> inside the slot-count sentence; match on the count alone.
    expect(await findByText('42')).toBeTruthy()
    expect(await findByText('2.0 KB')).toBeTruthy()
  })

  it('renders the push target when the generator pushed to an endpoint', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ endpoint: 'https://agg.example/ingest' })])
    vi.mocked(generateEpgExport).mockResolvedValue(
      generateOk({
        document: null,
        pushed_to: 'https://agg.example/ingest',
        pushed_at: '2026-06-18T12:00:00Z',
      }),
    )
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /generate epg-tv-guide/i }))
    expect(await findByText(/Pushed to/i)).toBeTruthy()
    expect(await findByText('https://agg.example/ingest')).toBeTruthy()
  })

  it('surfaces a push error on the result panel rather than as a 500', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ endpoint: 'https://agg.example/ingest' })])
    vi.mocked(generateEpgExport).mockResolvedValue(
      generateOk({ document: null, pushed_to: null, error: 'aggregator returned 503' }),
    )
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /generate epg-tv-guide/i }))
    expect(await findByText(/Push failed/i)).toBeTruthy()
    expect(await findByText(/aggregator returned 503/)).toBeTruthy()
  })
})

describe('EpgExportScreen delete confirm', () => {
  it('arms a confirm-delete control before deleting', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg()])
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^delete epg-tv-guide$/i }))
    const confirmBtn = await findByRole('button', { name: /confirm delete epg-tv-guide/i })
    fireEvent.click(confirmBtn)
    await waitFor(() => expect(vi.mocked(deleteEpgConfig)).toHaveBeenCalledWith('epg-tv-guide'))
  })

  it('renders a per-row warning that names the endpoint when the row is awaiting confirm', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ endpoint: 'https://agg.example/ingest' })])
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^delete epg-tv-guide$/i }))
    expect(
      await findByText(
        /Confirming will delete this EPG export config and stop pushing to https:\/\/agg\.example\/ingest/i,
      ),
    ).toBeTruthy()
  })

  it('renders the download-workflow phrasing when the row has no endpoint', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ endpoint: null })])
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^delete epg-tv-guide$/i }))
    expect(
      await findByText(/stop pushing to this download workflow/i),
    ).toBeTruthy()
  })
})

describe('EpgExportScreen inline download (Blob URL)', () => {
  it('builds a Blob object URL for the inline document and renders the Download link', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ endpoint: null })])
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /generate epg-tv-guide/i }))
    expect(await findByText(/Download document/i)).toBeTruthy()
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })
})

describe('EpgExportScreen cross-row generate disable', () => {
  it('disables Generate on every row while any one generate is in flight', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg({ config_id: 'epg-a' }), cfg({ config_id: 'epg-b' })])
    // Block the in-flight mutation so the disabled state is observable.
    // The Promise executor runs synchronously, so capturing the resolver this
    // way is safe. We cast the captured variable explicitly because TS's
    // control-flow narrowing collapses `resolve` to `never` when it's only
    // assigned inside a callback closure (a well-known limitation, see
    // microsoft/TypeScript#11498).
    let resolver: ((result: EpgGenerateResult) => void) | null = null
    vi.mocked(generateEpgExport).mockImplementation(
      () =>
        new Promise<EpgGenerateResult>((res) => {
          resolver = res
        }),
    )
    const { findByRole } = renderScreen()
    const aBtn = (await findByRole('button', { name: /generate epg-a/i })) as HTMLButtonElement
    const bBtn = (await findByRole('button', { name: /generate epg-b/i })) as HTMLButtonElement
    fireEvent.click(aBtn)
    await waitFor(() => expect(aBtn.disabled).toBe(true))
    expect(bBtn.disabled).toBe(true)
    // Release the in-flight mutation so the test teardown doesn't hang.
    const releaseResolver = resolver as ((result: EpgGenerateResult) => void) | null
    releaseResolver?.(generateOk())
  })
})

describe('EpgExportScreen edit', () => {
  it('disables the config_id input on edit and patches without changing config_id', async () => {
    vi.mocked(listEpgConfigs).mockResolvedValue([cfg()])
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /edit epg-tv-guide/i }))
    const cfgInput = (await findByLabelText('Config ID')) as HTMLInputElement
    expect(cfgInput.disabled).toBe(true)
    fireEvent.change(await findByLabelText('Channel ID'), { target: { value: 'pub-3' } })
    fireEvent.click(await findByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(vi.mocked(patchEpgConfig)).toHaveBeenCalled())
    const [id, patch] = vi.mocked(patchEpgConfig).mock.calls[0]
    expect(id).toBe('epg-tv-guide')
    expect(patch.channel_id).toBe('pub-3')
  })
})
