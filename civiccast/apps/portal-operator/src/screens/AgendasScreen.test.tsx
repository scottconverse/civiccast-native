// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  AgendaItem,
  MeetingAgenda,
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
  listMeetingAgendas: vi.fn(),
  createMeetingAgenda: vi.fn(),
  patchMeetingAgenda: vi.fn(),
  deleteMeetingAgenda: vi.fn(),
  listAgendaItems: vi.fn(),
  createAgendaItem: vi.fn(),
  patchAgendaItem: vi.fn(),
  deleteAgendaItem: vi.fn(),
  syncAgendaFromChapters: vi.fn(),
  importAgendaFromDoc: vi.fn(),
}))

import {
  ApiError,
  createAgendaItem,
  createMeetingAgenda,
  deleteAgendaItem,
  deleteMeetingAgenda,
  getStaffIdentity,
  importAgendaFromDoc,
  listAgendaItems,
  listMeetingAgendas,
  patchAgendaItem,
  patchMeetingAgenda,
  syncAgendaFromChapters,
} from '../api/client'
import { AgendasScreen } from './AgendasScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function agenda(overrides: Partial<MeetingAgenda> = {}): MeetingAgenda {
  return {
    agenda_id: 'council-2026-01',
    station_id: 'civiccast-station',
    meeting_asset_id: 'asset-council-2026-01',
    source_doc_url: null,
    status: 'draft',
    ...overrides,
  }
}

function item(overrides: Partial<AgendaItem> = {}): AgendaItem {
  return {
    item_id: 'item-01',
    agenda_id: 'council-2026-01',
    order: 0,
    number: '1',
    title: 'Call to order',
    video_timecode_s: 0,
    doc_anchor: null,
    notes: null,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgendasScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
  vi.mocked(listMeetingAgendas).mockResolvedValue([agenda()])
  vi.mocked(listAgendaItems).mockResolvedValue([])
  vi.mocked(createMeetingAgenda).mockImplementation(async (p) =>
    agenda({ agenda_id: p.agenda_id, meeting_asset_id: p.meeting_asset_id }),
  )
  vi.mocked(patchMeetingAgenda).mockImplementation(async (id, patch) =>
    agenda({ agenda_id: id, status: patch.status ?? 'draft' }),
  )
  vi.mocked(deleteMeetingAgenda).mockResolvedValue(undefined)
  vi.mocked(createAgendaItem).mockImplementation(async (agendaId, payload) =>
    // Spread first, then pin agenda_id so the typescript TS2783 "specified
    // more than once" warning does not fire; the test always wants the
    // mock to echo `agendaId` rather than whatever the payload carried.
    item({ ...payload, agenda_id: agendaId }),
  )
  vi.mocked(patchAgendaItem).mockImplementation(async (agendaId, itemId, patch) =>
    item({
      agenda_id: agendaId,
      item_id: itemId,
      title: patch.title ?? 'Call to order',
    }),
  )
  vi.mocked(deleteAgendaItem).mockResolvedValue(undefined)
  vi.mocked(syncAgendaFromChapters).mockResolvedValue([item({ item_id: 'item-02', order: 1 })])
  vi.mocked(importAgendaFromDoc).mockResolvedValue([
    item({ item_id: 'item-i-01', order: 0 }),
    item({ item_id: 'item-i-02', order: 1 }),
  ])
})

describe('AgendasScreen access', () => {
  it('shows the access banner for a non-author role and does not fetch agendas', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByText } = renderScreen()
    expect(
      await findByText(/records clerk or meeting operator role/i),
    ).toBeTruthy()
    expect(vi.mocked(listMeetingAgendas)).not.toHaveBeenCalled()
  })

  it('renders the picker and selected agenda card for an author role', async () => {
    const { findByLabelText, findAllByText } = renderScreen()
    expect(await findByLabelText('Pick an agenda')).toBeTruthy()
    // The agenda id renders in BOTH the picker option and the card heading;
    // we just assert at least one match (the card binds publish + delete to
    // it, so finding two is the happy path).
    const matches = await findAllByText(/council-2026-01/)
    expect(matches.length).toBeGreaterThan(0)
  })
})

// UX-3 fix: on the empty-state path the picker is hidden so the "No agendas
// yet" banner is the only empty-state surface. Without this assertion a
// regression that re-introduces the disabled placeholder option would slip.
describe('AgendasScreen empty state', () => {
  it('hides the agenda picker and shows the empty-state banner when the list is empty', async () => {
    vi.mocked(listMeetingAgendas).mockResolvedValue([])
    const { findByText, queryByLabelText } = renderScreen()
    expect(
      await findByText(/No agendas yet\. Use the form above to create one/i),
    ).toBeTruthy()
    // The whole picker `<select>` is gone — not just the placeholder option.
    expect(queryByLabelText('Pick an agenda')).toBeNull()
  })
})

// UX-4 fix: when a background refetch fails but cached items remain on screen,
// react-query keeps the rows AND flips `isError` true. The Banner-only path
// only fires for a cold cache; this stale-warning pill covers the hot cache.
describe('AgendasScreen stale-list warning (UX-4)', () => {
  it('shows the stale-list pill when items refetch fails after a successful load', async () => {
    vi.mocked(listAgendaItems)
      .mockResolvedValueOnce([item()])
      .mockRejectedValue(new ApiError('Request failed: 503', 503, 'service unavailable'))
    const { findByRole, findByText } = renderScreen()
    // Wait for the table to render the first item.
    await findByText('Call to order')
    // Trigger a refetch by hitting Sync from chapters; the mock above fails
    // on subsequent listAgendaItems calls.
    vi.mocked(syncAgendaFromChapters).mockResolvedValue([])
    fireEvent.click(
      await findByRole('button', { name: /sync agenda items from chapter markers/i }),
    )
    expect(
      await findByText(/Items list may be stale — last refresh failed/i),
    ).toBeTruthy()
  })
})

// T-8 fix: list-load failure surfaces as the warn banner, not a silent empty.
describe('AgendasScreen list failures (T-8)', () => {
  it('surfaces a warn banner when listAgendaItems rejects on a cold cache', async () => {
    vi.mocked(listAgendaItems).mockRejectedValue(
      new ApiError('Request failed: 503', 503, 'agenda items unavailable'),
    )
    const { findByText } = renderScreen()
    expect(await findByText(/agenda items unavailable/i)).toBeTruthy()
  })
})

describe('AgendasScreen create agenda', () => {
  it('submits the create payload with station + slug fields', async () => {
    vi.mocked(listMeetingAgendas).mockResolvedValue([])
    const { findByLabelText, getByRole } = renderScreen()
    fireEvent.change(await findByLabelText('Agenda ID'), {
      target: { value: 'planning-2026-02' },
    })
    fireEvent.change(await findByLabelText('Meeting asset ID'), {
      target: { value: 'asset-planning-2026-02' },
    })
    fireEvent.change(await findByLabelText('Source doc URL'), {
      target: { value: 'https://example.gov/p.pdf' },
    })
    fireEvent.click(getByRole('button', { name: /create agenda/i }))
    await waitFor(() =>
      expect(vi.mocked(createMeetingAgenda)).toHaveBeenCalledWith({
        agenda_id: 'planning-2026-02',
        station_id: 'civiccast-station',
        meeting_asset_id: 'asset-planning-2026-02',
        source_doc_url: 'https://example.gov/p.pdf',
      }),
    )
  })
})

describe('AgendasScreen publish gate', () => {
  it('disables Publish when the agenda has no items', async () => {
    const { findByRole } = renderScreen()
    const publish = (await findByRole('button', { name: /publish this agenda/i })) as HTMLButtonElement
    expect(publish.disabled).toBe(true)
  })

  it('enables Publish when there is at least one item and fires the patch', async () => {
    vi.mocked(listAgendaItems).mockResolvedValue([item()])
    const { findByRole } = renderScreen()
    const publish = (await findByRole('button', { name: /publish this agenda/i })) as HTMLButtonElement
    await waitFor(() => expect(publish.disabled).toBe(false))
    fireEvent.click(publish)
    await waitFor(() =>
      expect(vi.mocked(patchMeetingAgenda)).toHaveBeenCalledWith(
        'council-2026-01',
        { status: 'published' },
      ),
    )
  })

  it('surfaces the 422 message verbatim when the backend refuses publish', async () => {
    vi.mocked(listAgendaItems).mockResolvedValue([item()])
    vi.mocked(patchMeetingAgenda).mockRejectedValue(
      new ApiError('Request failed: 422', 422, 'Agenda has zero items; add one before publish.'),
    )
    const { findByRole, findByText } = renderScreen()
    const publish = (await findByRole('button', { name: /publish this agenda/i })) as HTMLButtonElement
    await waitFor(() => expect(publish.disabled).toBe(false))
    fireEvent.click(publish)
    expect(await findByText(/agenda has zero items; add one before publish/i)).toBeTruthy()
  })
})

describe('AgendasScreen delete agenda confirm', () => {
  it('requires a two-step confirm and shows the cascade warning between steps', async () => {
    const { findByRole, findByText, queryByRole } = renderScreen()
    // First click: arm — backend not called yet.
    fireEvent.click(await findByRole('button', { name: /delete this agenda/i }))
    expect(
      await findByText(/Confirming will also delete every item under this agenda/i),
    ).toBeTruthy()
    expect(vi.mocked(deleteMeetingAgenda)).not.toHaveBeenCalled()
    // Second click: actually delete.
    fireEvent.click(await findByRole('button', { name: /confirm delete agenda/i }))
    await waitFor(() =>
      expect(vi.mocked(deleteMeetingAgenda)).toHaveBeenCalledWith('council-2026-01'),
    )
    // After successful delete the confirm button is gone.
    await waitFor(() => expect(queryByRole('button', { name: /confirm delete agenda/i })).toBeNull())
  })
})

describe('AgendasScreen item create', () => {
  it('creates an item with the typed payload against the selected agenda', async () => {
    const { findByLabelText, getByRole } = renderScreen()
    fireEvent.change(await findByLabelText('Item ID'), { target: { value: 'item-77' } })
    fireEvent.change(await findByLabelText('Order'), { target: { value: '3' } })
    fireEvent.change(await findByLabelText('Title'), { target: { value: 'Public comment' } })
    fireEvent.change(await findByLabelText('Video timecode (seconds)'), {
      target: { value: '420' },
    })
    fireEvent.click(getByRole('button', { name: /^add item$/i }))
    await waitFor(() =>
      expect(vi.mocked(createAgendaItem)).toHaveBeenCalledWith(
        'council-2026-01',
        expect.objectContaining({
          item_id: 'item-77',
          agenda_id: 'council-2026-01',
          order: 3,
          title: 'Public comment',
          video_timecode_s: 420,
        }),
      ),
    )
  })
})

describe('AgendasScreen sync from chapters', () => {
  it('calls the sync endpoint and shows the seeded-count success banner', async () => {
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(
      await findByRole('button', { name: /sync agenda items from chapter markers/i }),
    )
    await waitFor(() =>
      expect(vi.mocked(syncAgendaFromChapters)).toHaveBeenCalledWith('council-2026-01'),
    )
    expect(await findByText(/Synced 1 new item from chapter markers/i)).toBeTruthy()
  })
})

describe('AgendasScreen import from doc', () => {
  it('submits the textarea body as text/plain and shows the import-count banner', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    const pasted = '1. Call to order\n2. Approval of minutes'
    fireEvent.change(await findByLabelText('Plain-text agenda to import'), {
      target: { value: pasted },
    })
    fireEvent.click(await findByRole('button', { name: /import agenda items from pasted text/i }))
    await waitFor(() =>
      expect(vi.mocked(importAgendaFromDoc)).toHaveBeenCalledWith('council-2026-01', pasted),
    )
    expect(await findByText(/Imported 2 items from the pasted text/i)).toBeTruthy()
  })

  it('renders the plain-text-only follow-up message when the server returns 415', async () => {
    vi.mocked(importAgendaFromDoc).mockRejectedValue(
      new ApiError('Request failed: 415', 415, 'PDF/DOCX not supported.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Plain-text agenda to import'), {
      target: { value: 'anything' },
    })
    fireEvent.click(await findByRole('button', { name: /import agenda items from pasted text/i }))
    expect(
      await findByText(
        /Only plain-text agendas import here today\. PDF support is a follow-up\./i,
      ),
    ).toBeTruthy()
  })
})
