import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    createSupportBundle: vi.fn(),
    downloadSupportBundle: vi.fn(),
  }
})

import { createSupportBundle, downloadSupportBundle } from '../api/client'
import { SupportBundlePanel } from './SystemHealthScreen'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:civiccast-support-bundle'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

describe('SupportBundlePanel', () => {
  it('downloads the generated redacted bundle to the tester computer', async () => {
    vi.mocked(createSupportBundle).mockResolvedValue({
      bundle_id: 'support-20260716T173104Z-dab70659',
      generated_at: '2026-07-16T17:31:04Z',
      path: '/var/lib/civiccast/storage/support-bundles/support-20260716T173104Z-dab70659.json',
      sha256: 'a'.repeat(64),
      redacted: true,
      contains: ['system health'],
      excludes: ['secrets'],
      next_step: 'Attach this bundle to support.',
    })
    vi.mocked(downloadSupportBundle).mockResolvedValue(
      new Blob(['{"redacted":true}'], { type: 'application/json' }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { findByRole, getByRole } = render(
      <QueryClientProvider client={client}>
        <SupportBundlePanel canCreate />
      </QueryClientProvider>,
    )

    fireEvent.click(getByRole('button', { name: 'Create support bundle' }))
    const downloadButton = await findByRole('button', { name: 'Download support bundle' })
    fireEvent.click(downloadButton)

    await waitFor(() => {
      expect(downloadSupportBundle).toHaveBeenCalledWith(
        'support-20260716T173104Z-dab70659',
      )
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    })
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:civiccast-support-bundle')
  })
})
