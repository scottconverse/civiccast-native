// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HashRouter, MemoryRouter } from 'react-router'

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
  getManual: vi.fn(),
}))

import { getManual } from '../api/client'
import type { ManualDocument } from '../types/api.generated'
import { ManualScreen } from './ManualScreen'

function manual(overrides: Partial<ManualDocument> = {}): ManualDocument {
  return {
    source: 'docs/USER-MANUAL.md',
    source_sha256: 'a'.repeat(64),
    generated_at: '2026-08-29T00:00:00Z',
    toc: [
      { id: 'section-a-end-user-guide', level: 2, title: 'Section A — End-User Guide' },
      { id: 'app-glossary', level: 3, title: 'Glossary' },
      { id: 'cdn-and-provider-options', level: 4, title: 'CDN and provider options' },
    ],
    html:
      '<h2 id="section-a-end-user-guide">Section A — End-User Guide</h2>' +
      '<h3 id="app-glossary">Glossary</h3><p>Plain-language definitions.</p>' +
      '<p><a href="#app-glossary">Jump to glossary</a></p>' +
      '<h4 id="cdn-and-provider-options">CDN and provider options</h4><p>Use the concierge box.</p>',
    ...overrides,
  }
}

function renderScreen(initialEntries: string[] = ['/help']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <ManualScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderHashScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <HashRouter>
        <ManualScreen />
      </HashRouter>
    </QueryClientProvider>,
  )
}

describe('ManualScreen', () => {
  it('shows a loading state before the manual arrives', () => {
    vi.mocked(getManual).mockReturnValue(new Promise(() => {}))
    renderScreen()
    expect(screen.getByRole('status').textContent).toMatch(/loading the operator manual/i)
  })

  it('renders the table of contents and the manual body once loaded', async () => {
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen()

    const nav = await screen.findByRole('navigation', { name: /manual contents/i })
    expect(within(nav).getByText('Glossary')).toBeTruthy()
    expect(within(nav).getByText(/CDN and provider options/)).toBeTruthy()

    expect(await screen.findByText('Plain-language definitions.')).toBeTruthy()
    expect(screen.getByText('Use the concierge box.')).toBeTruthy()
  })

  it('shows an error state when the manual fails to load', async () => {
    vi.mocked(getManual).mockRejectedValue(new Error('offline'))
    renderScreen()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/manual could not load/i)
  })

  it('filters the table of contents by title', async () => {
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen()

    const nav = await screen.findByRole('navigation', { name: /manual contents/i })
    expect(within(nav).getByText('Glossary')).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText(/filter by section title/i), {
      target: { value: 'CDN' },
    })

    expect(within(nav).queryByText('Glossary')).toBeNull()
    expect(within(nav).getByText(/CDN and provider options/)).toBeTruthy()
  })

  it('deep-links from a URL hash to the matching manual section', async () => {
    // jsdom does not implement Element.scrollIntoView; stub it so the
    // component's deep-link effect can run without a console error, then
    // assert on the TOC entry it marks active rather than on scroll math.
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen(['/help#app-glossary'])

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled()
    })
    const nav = screen.getByRole('navigation', { name: /manual contents/i })
    const activeLink = within(nav).getByText('Glossary').closest('a')
    expect(activeLink?.getAttribute('aria-current')).toBe('location')
  })

  it('every TOC entry is a real link with an href, not a JS-only click handler', async () => {
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen()

    const nav = await screen.findByRole('navigation', { name: /manual contents/i })
    const glossaryLink = within(nav).getByText('Glossary').closest('a')
    // A real href (not "#" or javascript:) so ctrl/middle-click "open in a
    // new tab" and "Copy link" work like any other link -- PR #74 review:
    // the previous version used a raw <a> whose href resolved from the
    // component's own manualLink() helper but was intercepted with
    // preventDefault(), so those native affordances silently broke.
    expect(glossaryLink?.getAttribute('href')).toBe('/help#app-glossary')
  })

  it('clicking a TOC entry navigates and scrolls to the matching section', async () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen()

    const nav = await screen.findByRole('navigation', { name: /manual contents/i })
    fireEvent.click(within(nav).getByText('Glossary'))

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    const activeLink = within(nav).getByText('Glossary').closest('a')
    expect(activeLink?.getAttribute('aria-current')).toBe('location')
  })

  it('keeps an injected manual fragment link inside HashRouter and scrolls to its section', async () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    vi.mocked(getManual).mockResolvedValue(manual())
    window.history.replaceState({}, '', '#/help')
    renderHashScreen()

    const link = await screen.findByRole('link', { name: 'Jump to glossary' })
    await waitFor(() => expect(link.getAttribute('href')).toBe('#/help#app-glossary'))
    fireEvent.click(link)

    await waitFor(() => {
      expect(window.location.hash).toBe('#/help#app-glossary')
      expect(scrollIntoView).toHaveBeenCalled()
    })
    // React re-renders the manual body when the deep-link target becomes
    // active. The href must stay router-aware afterward so copying it or
    // opening it in a new tab does not turn it into a broken root fragment.
    expect(screen.getByRole('link', { name: 'Jump to glossary' }).getAttribute('href')).toBe(
      '#/help#app-glossary',
    )
  })
})
