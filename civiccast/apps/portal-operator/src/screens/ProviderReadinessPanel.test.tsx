// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

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
  getProviderReadiness: vi.fn(),
  saveProviderCredentials: vi.fn(),
  recordProviderProof: vi.fn(),
  testProviderConnection: vi.fn(),
  provisionR2Concierge: vi.fn(),
}))

import { getProviderReadiness } from '../api/client'
import type { ProviderReadinessItem, ProviderReadinessReport } from '../types/api.generated'
import { ProviderReadinessPanel } from './SetupScreen'

function item(overrides: Partial<ProviderReadinessItem> = {}): ProviderReadinessItem {
  return {
    id: 'internet-archive',
    label: 'Internet Archive',
    required: false,
    status: 'not_set_up',
    message: 'Internet Archive is optional. Skip it for now if the station doesn\'t need it yet.',
    next_step: 'Optional. Paste your own Internet Archive keys, then run a live proof.',
    what_you_need: ['A free Internet Archive account', 'Your own S3-style access key and secret key'],
    setup_steps: ['Create or sign in.', 'Copy the keys.', 'Paste them below.'],
    ...overrides,
  }
}

function report(items: ProviderReadinessItem[]): ProviderReadinessReport {
  return {
    generated_at: '2026-08-29T00:00:00Z',
    items,
    next_step: 'Set up only the providers the station needs.',
  }
}

function renderPanel(items: ProviderReadinessItem[], canManageProviders = true) {
  vi.mocked(getProviderReadiness).mockResolvedValue(report(items))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProviderReadinessPanel canManageProviders={canManageProviders} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProviderReadinessPanel manual cross-links', () => {
  it('links a provider card with manual_section to its /help#<anchor>', async () => {
    renderPanel([item({ manual_section: 'provider-internet-archive' })])

    const link = await screen.findByRole('link', { name: /read more in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#provider-internet-archive')
  })

  it('omits the manual link for a card with no manual_section', async () => {
    renderPanel([item({ manual_section: null, label: 'Untitled Provider' })])

    expect(await screen.findByText('Untitled Provider')).toBeTruthy()
    expect(screen.queryByRole('link', { name: /read more in the manual/i })).toBeNull()
  })

  it('does not use "Ask the technical admin" style hand-off copy', async () => {
    renderPanel([
      item({
        id: 'cloudflare-r2',
        label: 'Cloudflare R2',
        manual_section: 'provider-cloudflare-r2',
        setup_steps: [
          'Use the CDN concierge box on this card: create a free Cloudflare account.',
          'Create one API token scoped to R2 Edit, then paste it in and click Provision for me.',
        ],
      }),
    ])

    const panel = await screen.findByText('Cloudflare R2')
    const section = panel.closest('article')
    expect(section).toBeTruthy()
    expect(within(section as HTMLElement).queryByText(/ask the technical admin/i)).toBeNull()
  })

  it('marks an optional, not-set-up provider as safe to skip', async () => {
    renderPanel([item()])

    expect(await screen.findByText(/skip it for now/i)).toBeTruthy()
  })
})
