// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { MeetingAgendaSidebar } from './MeetingAgendaSidebar'
import type { PublicMeetingAgenda } from './types'

// vitest in this repo runs without testing-library's global afterEach (the
// public portal config inherits the operator portal's pattern — see
// test-setup.ts); call cleanup explicitly so renders don't leak.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function mockFetchOk(body: unknown) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch
}

function mockFetchStatus(status: number, detail = 'not found') {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ detail }), {
      status,
      statusText: status === 404 ? 'Not Found' : 'Error',
      headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch
}

// Returns a fetch mock that never resolves until `resolve()` is called.
// Used to assert the transient `role="status"` loading branch (T-2 fix:
// the suite previously never proved the loading UI rendered).
function mockFetchPending(): { resolve: (response: Response) => void } {
  let resolveFn!: (response: Response) => void
  const pending = new Promise<Response>((res) => {
    resolveFn = res
  })
  globalThis.fetch = vi.fn(() => pending) as unknown as typeof fetch
  return { resolve: resolveFn }
}

const baseAgenda: PublicMeetingAgenda = {
  agenda_id: 'ag-1',
  meeting_asset_id: 'asset-1',
  source_doc_url: null,
  items: [
    {
      item_id: 'i1',
      order: 0,
      number: '1',
      title: 'Roll call',
      video_timecode_s: 0,
      doc_anchor: null,
    },
    {
      item_id: 'i2',
      order: 1,
      number: '2',
      title: 'Awaiting timecode',
      video_timecode_s: null,
      doc_anchor: null,
    },
    {
      item_id: 'i3',
      order: 2,
      number: '3.a',
      title: 'Approve minutes',
      video_timecode_s: 3725,
      doc_anchor: null,
    },
  ],
}

describe('MeetingAgendaSidebar', () => {
  beforeEach(() => {
    // jsdom doesn't provide HTMLElement.focus side-effects we depend on for
    // keyboard nav assertions; the default behavior is fine, but make sure
    // each test starts with a clean active element.
    document.body.innerHTML = ''
  })

  it('renders nothing when the public agenda endpoint returns 404', async () => {
    mockFetchStatus(404, 'No published agenda for meeting asset')
    const onSeek = vi.fn()
    const { container } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    await waitFor(() => {
      expect(container.querySelector('aside')).toBeNull()
    })
    expect(container.textContent).not.toContain('Agenda')
  })

  it('renders the heading + each item on a 200 response', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByText, getByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    await findByText('Agenda')
    expect(getByRole('button', { name: 'Jump to 1 Roll call' })).toBeTruthy()
    expect(getByRole('button', { name: 'Jump to 3.a Approve minutes' })).toBeTruthy()
  })

  it('formats timecodes as HH:MM:SS and disables items without a timecode', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole, getByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    await findByRole('button', { name: 'Jump to 1 Roll call' })
    const disabledBtn = getByRole('button', { name: 'Jump to 2 Awaiting timecode' })
    expect(disabledBtn.getAttribute('aria-disabled')).toBe('true')
    expect(disabledBtn.getAttribute('tabindex')).toBe('-1')
    expect((disabledBtn as HTMLButtonElement).disabled).toBe(true)
    // 3725s = 01:02:05
    const seekable = getByRole('button', { name: 'Jump to 3.a Approve minutes' })
    expect(seekable.textContent).toContain('01:02:05')
  })

  it('calls onSeek with the item timecode when an item is clicked', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const btn = await findByRole('button', { name: 'Jump to 3.a Approve minutes' })
    fireEvent.click(btn)
    expect(onSeek).toHaveBeenCalledTimes(1)
    expect(onSeek).toHaveBeenCalledWith(3725)
  })

  it('does not call onSeek when a disabled (no-timecode) item is clicked', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const btn = await findByRole('button', { name: 'Jump to 2 Awaiting timecode' })
    fireEvent.click(btn)
    expect(onSeek).not.toHaveBeenCalled()
  })

  it('ArrowDown skips disabled items and lands on the next seekable one', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole, getByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const first = await findByRole('button', { name: 'Jump to 1 Roll call' })
    first.focus()
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: 'ArrowDown' })
    const third = getByRole('button', { name: 'Jump to 3.a Approve minutes' })
    expect(document.activeElement).toBe(third)
  })

  it('Home / End jump to the first / last seekable items', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole, getByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const third = await findByRole('button', { name: 'Jump to 3.a Approve minutes' })
    third.focus()
    fireEvent.keyDown(third, { key: 'Home' })
    expect(document.activeElement).toBe(getByRole('button', { name: 'Jump to 1 Roll call' }))
    fireEvent.keyDown(document.activeElement as Element, { key: 'End' })
    expect(document.activeElement).toBe(
      getByRole('button', { name: 'Jump to 3.a Approve minutes' }),
    )
  })

  it('renders the source_doc_url link with rel="noopener noreferrer" and target="_blank"', async () => {
    mockFetchOk({
      ...baseAgenda,
      source_doc_url: 'https://example.gov/agenda.pdf',
    })
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const link = await findByRole('link', { name: 'Agenda document' })
    expect(link.getAttribute('href')).toBe('https://example.gov/agenda.pdf')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(link.getAttribute('target')).toBe('_blank')
  })

  it('does not render an agenda-document link when source_doc_url is null', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByText, queryByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    await findByText('Agenda')
    expect(queryByRole('link', { name: 'Agenda document' })).toBeNull()
  })

  // ---------------------------------------------------------------------
  // T-2 / T-7 fix: cover the previously-untested loading and error runtime
  // branches AND prove the absent-vs-error discrimination now uses the
  // FetchError status (refactor away from the message-regex). Without these
  // tests, a 5xx incident could regress into a silent "absent" or stuck
  // "loading" branch and the suite would still pass.
  // ---------------------------------------------------------------------

  it('renders the loading announcement before the fetch resolves (T-2)', async () => {
    const pending = mockFetchPending()
    const onSeek = vi.fn()
    const { getByRole, findByText } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    // The transient `role="status"` element should render synchronously
    // because the fetch promise has not resolved yet.
    const status = getByRole('status')
    expect(status.textContent).toMatch(/loading agenda/i)
    // Resolve so the test does not leak a dangling promise.
    pending.resolve(
      new Response(JSON.stringify(baseAgenda), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await findByText('Agenda')
  })

  it('renders the error alert when the public endpoint returns 500 (T-2)', async () => {
    mockFetchStatus(500, 'internal server error')
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const alert = await findByRole('alert')
    expect(alert.textContent).toMatch(/could not be loaded/i)
  })

  it('renders the error alert when the public endpoint returns 503 (T-2)', async () => {
    mockFetchStatus(503, 'service unavailable')
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const alert = await findByRole('alert')
    expect(alert.textContent).toMatch(/could not be loaded/i)
  })

  it('treats a non-404 server error as "error", not "absent" (T-7 status discrimination)', async () => {
    // The error body intentionally contains the word "not found" so the
    // legacy regex-discriminator would mis-classify it as absent. The
    // status-based discriminator should still surface the error UI.
    mockFetchStatus(502, 'upstream not found something happened')
    const onSeek = vi.fn()
    const { findByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const alert = await findByRole('alert')
    expect(alert.textContent).toMatch(/could not be loaded/i)
  })

  // T-5 fix: ArrowUp was previously uncovered; a regression that flipped
  // the direction or stopped skipping disabled items would not be caught.
  it('ArrowUp skips disabled items and lands on the previous seekable one (T-5)', async () => {
    mockFetchOk(baseAgenda)
    const onSeek = vi.fn()
    const { findByRole, getByRole } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const third = await findByRole('button', { name: 'Jump to 3.a Approve minutes' })
    third.focus()
    expect(document.activeElement).toBe(third)
    fireEvent.keyDown(third, { key: 'ArrowUp' })
    const first = getByRole('button', { name: 'Jump to 1 Roll call' })
    expect(document.activeElement).toBe(first)
  })

  // ---------------------------------------------------------------------
  // UX-2 / DC-4: PDF source docs render in an iframe beside the player
  // (inside the sidebar column). Non-PDF URLs still render the link only.
  // ---------------------------------------------------------------------

  it('embeds the source doc in an iframe when source_doc_url ends in .pdf (UX-2)', async () => {
    mockFetchOk({
      ...baseAgenda,
      source_doc_url: 'https://example.gov/agenda.pdf',
    })
    const onSeek = vi.fn()
    const { findByTitle } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const frame = await findByTitle('Agenda document')
    expect(frame.tagName).toBe('IFRAME')
    expect(frame.getAttribute('src')).toBe('https://example.gov/agenda.pdf')
    // a11y: the iframe MUST carry a title attribute.
    expect(frame.getAttribute('title')).toBe('Agenda document')
  })

  it('embeds the iframe even when the PDF URL has query/fragment suffixes', async () => {
    mockFetchOk({
      ...baseAgenda,
      source_doc_url: 'https://example.gov/agenda.pdf?token=abc#page=3',
    })
    const onSeek = vi.fn()
    const { findByTitle } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const frame = await findByTitle('Agenda document')
    expect(frame.tagName).toBe('IFRAME')
  })

  it('falls back to the link when source_doc_url is NOT a PDF (UX-2)', async () => {
    mockFetchOk({
      ...baseAgenda,
      source_doc_url: 'https://example.gov/agenda.html',
    })
    const onSeek = vi.fn()
    const { findByRole, queryByTitle } = render(
      <MeetingAgendaSidebar meeting_asset_id="asset-1" onSeek={onSeek} />,
    )
    const link = await findByRole('link', { name: 'Agenda document' })
    expect(link.getAttribute('href')).toBe('https://example.gov/agenda.html')
    // No iframe — the URL is not a PDF.
    expect(queryByTitle('Agenda document')).toBeNull()
  })
})
