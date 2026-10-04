// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HashRouter, MemoryRouter, useLocation, useNavigate } from 'react-router'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
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
  manualImageUrl: (path: string) => path,
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
      { id: 'glossary', level: 3, title: 'Glossary' },
      { id: 'provider-cloudflare-r2', level: 4, title: 'Cloudflare R2 (recommended, usually free)' },
    ],
    html:
      '<h2 id="section-a-end-user-guide">Section A — End-User Guide</h2>' +
      '<h3 id="glossary">Glossary</h3><p>Plain-language definitions.</p>' +
      '<h4 id="provider-cloudflare-r2">Cloudflare R2 (recommended, usually free)</h4><p>Use the concierge box.</p>',
    ...overrides,
  }
}

function LocationMarker() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><div role="note" aria-label="Current route">{location.pathname}{location.hash}</div><button onClick={() => navigate(-1)}>Harness Back</button></>
}

function largeManual(): ManualDocument {
  const toc: ManualDocument['toc'] = []
  for (let part = 0; part < 5; part++) {
    toc.push({ id: `part-${part}`, level: 1, title: `Part ${part}` })
    for (let chapter = 0; chapter < 7; chapter++) {
      const key = `${part}-${chapter}`
      toc.push({ id: `chapter-${key}`, level: 2, title: `Chapter ${key}` })
      for (let section = 0; section < 17; section++) {
        toc.push({ id: `section-${key}-${section}`, level: 3 + section % 4, title: `Section ${key}-${section}` })
      }
    }
  }
  // Same scale and level range as the real five-part, 35-chapter manual.
  return manual({ toc, html: toc.map((entry) => `<h${entry.level} id="${entry.id}">${entry.title}</h${entry.level}>`).join('') })
}

function renderScreen(initialEntries: string[] = ['/help'], hashRouter = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const contents = <><ManualScreen /><LocationMarker /></>
  if (hashRouter) window.history.replaceState(null, '', '/operator/#/help')
  return render(
    <QueryClientProvider client={client}>
      {hashRouter ? <HashRouter>{contents}</HashRouter> :
        <MemoryRouter initialEntries={initialEntries}>{contents}</MemoryRouter>}
    </QueryClientProvider>,
  )
}

describe('ManualScreen', () => {
  it('commits expanded chapter layout before scrolling a deep section', async () => {
    let linksAtScroll = 0
    Element.prototype.scrollIntoView = vi.fn(() => {
      linksAtScroll = within(screen.getByRole('navigation', { name: 'Manual contents' })).getAllByRole('link').length
    })
    vi.mocked(getManual).mockResolvedValue(largeManual())
    renderScreen(['/help#section-2-4-9'])
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled())
    expect(linksAtScroll).toBe(57)
  })

  it('keeps wide manual tables in named keyboard-accessible overflow regions', async () => {
    const content = manual()
    content.html += '<table><caption>Provider comparison</caption><tbody><tr><td>Wide details</td></tr></tbody></table>'
    vi.mocked(getManual).mockResolvedValue(content)
    renderScreen()
    const table = await screen.findByRole('table', { name: 'Provider comparison' })
    const region = table.parentElement!
    expect(region.getAttribute('role')).toBe('region')
    expect(region.getAttribute('aria-label')).toBe('Scrollable manual table 1')
    expect(region.tabIndex).toBe(0)
    expect(region.classList.contains('cc-manual-table-scroll')).toBe(true)
  })

  it('keeps the 635-heading manual to parts and chapters until expanded', async () => {
    const content = largeManual()
    expect(content.toc).toHaveLength(635)
    vi.mocked(getManual).mockResolvedValue(content)
    renderScreen()
    const nav = await screen.findByRole('navigation', { name: 'Manual contents' })
    expect(within(nav).getAllByRole('link')).toHaveLength(40)
    expect(within(nav).queryByRole('link', { name: 'Section 0-0-0' })).toBeNull()
    const expand = within(nav).getByRole('button', { name: 'Show sections for Chapter 0-0' })
    expect(expand.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(expand)
    expect(expand.getAttribute('aria-expanded')).toBe('true')
    expect(document.getElementById(expand.getAttribute('aria-controls')!)).toBeTruthy()
    expect(within(nav).getAllByRole('link')).toHaveLength(57)
    fireEvent.click(within(nav).getByRole('button', { name: 'Hide sections for Chapter 0-0' }))
    expect(within(nav).getAllByRole('link')).toHaveLength(40)
  })

  it('expands only the reading chapter for a deep link and chapter navigation', async () => {
    Element.prototype.scrollIntoView = vi.fn()
    vi.mocked(getManual).mockResolvedValue(largeManual())
    renderScreen(['/help#section-2-4-9'])
    const nav = await screen.findByRole('navigation', { name: 'Manual contents' })
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'Section 2-4-9' }).getAttribute('aria-current')).toBe('location'))
    expect(within(nav).getAllByRole('link')).toHaveLength(57)
    expect(within(nav).queryByRole('link', { name: 'Section 0-0-0' })).toBeNull()
    fireEvent.click(within(nav).getByRole('link', { name: 'Chapter 1-1' }))
    await waitFor(() => expect(within(nav).getByRole('link', { name: 'Section 1-1-0' })).toBeTruthy())
    expect(within(nav).queryByRole('link', { name: 'Section 2-4-9' })).toBeNull()
    expect(within(nav).getAllByRole('link')).toHaveLength(57)
  })

  it('title filtering finds collapsed deep sections and restores grouped contents', async () => {
    vi.mocked(getManual).mockResolvedValue(largeManual())
    renderScreen()
    const nav = await screen.findByRole('navigation', { name: 'Manual contents' })
    const filter = screen.getByRole('searchbox', { name: 'Filter sections by title' })
    fireEvent.change(filter, { target: { value: 'Section 4-6-16' } })
    expect(within(nav).getAllByRole('link')).toHaveLength(1)
    expect(within(nav).getByRole('link', { name: 'Section 4-6-16' })).toBeTruthy()
    fireEvent.change(filter, { target: { value: 'no matching title' } })
    expect(within(nav).queryAllByRole('link')).toHaveLength(0)
    expect(within(nav).getByText(/No section title matches/)).toBeTruthy()
    fireEvent.change(filter, { target: { value: '' } })
    expect(within(nav).getAllByRole('link')).toHaveLength(40)
  })

  it.each([false, true])('repeated body section clicks scroll again (hash=%s)', async (hashRouter) => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const content = manual()
    content.html += '<a href="#glossary">Read definitions</a>'
    vi.mocked(getManual).mockResolvedValue(content)
    renderScreen(['/help'], hashRouter)
    const link = await screen.findByRole('link', { name: 'Read definitions' })
    fireEvent.click(link)
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
    scroll.mockClear() // user has scrolled away; a second action must scroll anew
    fireEvent.click(screen.getByRole('link', { name: 'Read definitions' }))
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1))
  })

  it.each([false, true])('Back to unanchored manual clears current section (hash=%s)', async (hashRouter) => {
    Element.prototype.scrollIntoView = vi.fn()
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen(['/help'], hashRouter)
    const nav = await screen.findByRole('navigation', { name: 'Manual contents' })
    fireEvent.click(within(nav).getByText('Glossary'))
    await waitFor(() => expect(within(nav).getByText('Glossary').closest('a')?.getAttribute('aria-current')).toBe('location'))
    fireEvent.click(screen.getByRole('button', { name: 'Harness Back' }))
    await waitFor(() => expect(screen.getByLabelText('Current route').textContent).toBe('/help'))
    await waitFor(() => expect(nav.querySelector('[aria-current]')).toBeNull())
  })
  it.each([false, true])('body section links retain router navigation and native href (hash=%s)', async (hashRouter) => {
    Element.prototype.scrollIntoView = vi.fn()
    const content = manual()
    content.html += '<a href="#glossary"><strong>Read definitions</strong></a>'
    vi.mocked(getManual).mockResolvedValue(content)
    renderScreen(['/help'], hashRouter)
    const link = await screen.findByRole('link', { name: 'Read definitions' })
    await waitFor(() => expect(link.getAttribute('href')).toBe(hashRouter ? '#/help#glossary' : '/help#glossary'))
    // React must leave modified clicks native. Cancel only after observing that
    // boundary so jsdom does not attempt its unsupported new-tab navigation.
    const nativeClick = vi.fn((event: MouseEvent) => {
      expect(event.defaultPrevented).toBe(false)
      event.preventDefault()
    })
    document.addEventListener('click', nativeClick, { once: true })
    fireEvent.click(link, { ctrlKey: true })
    expect(nativeClick).toHaveBeenCalledOnce()
    expect(screen.getByLabelText('Current route').textContent).toBe('/help')
    fireEvent.click(within(link).getByText('Read definitions'))
    await waitFor(() => expect(screen.getByLabelText('Current route').textContent).toBe('/help#glossary'))
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled())
  })

  it('external body links preserve the console with safe new-tab attributes', async () => {
    const content = manual()
    content.html += '<a href="https://example.org/guide">External guide</a><a href="mailto:staff@example.org">Email staff</a>'
    vi.mocked(getManual).mockResolvedValue(content)
    renderScreen()
    const link = await screen.findByRole('link', { name: 'External guide' })
    await waitFor(() => expect(link.getAttribute('target')).toBe('_blank'))
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(screen.getByRole('link', { name: 'Email staff' }).getAttribute('target')).toBeNull()
  })

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
    expect(within(nav).getByText(/Cloudflare R2/)).toBeTruthy()

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
    fireEvent.change(screen.getByPlaceholderText(/filter sections by title/i), {
      target: { value: 'cloudflare' },
    })

    expect(within(nav).queryByText('Glossary')).toBeNull()
    expect(within(nav).getByText(/Cloudflare R2/)).toBeTruthy()
  })

  it('deep-links from a URL hash to the matching manual section', async () => {
    // jsdom does not implement Element.scrollIntoView; stub it so the
    // component's deep-link effect can run without a console error, then
    // assert on the TOC entry it marks active rather than on scroll math.
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    vi.mocked(getManual).mockResolvedValue(manual())
    renderScreen(['/help#glossary'])

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
    expect(glossaryLink?.getAttribute('href')).toBe('/help#glossary')
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
})
