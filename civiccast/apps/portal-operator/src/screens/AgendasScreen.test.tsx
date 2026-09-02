// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  AgendaItem,
  ExternalMeetingSummary,
  MeetingAgenda,
  StaffIdentityResponse,
} from '../types/api.generated'

afterEach(cleanup)

vi.mock('../api/client', () => ({
  AGENDA_EXTERNAL_SOURCES: ['legistar', 'primegov', 'civicclerk', 'js_portal'],
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
  getJsPortalPosture: vi.fn(),
  listExternalAgendaMeetings: vi.fn(),
  importExternalAgenda: vi.fn(),
}))

import {
  ApiError,
  createAgendaItem,
  createMeetingAgenda,
  deleteAgendaItem,
  deleteMeetingAgenda,
  getJsPortalPosture,
  getStaffIdentity,
  importAgendaFromDoc,
  importExternalAgenda,
  listAgendaItems,
  listExternalAgendaMeetings,
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

function externalMeeting(
  overrides: Partial<ExternalMeetingSummary> = {},
): ExternalMeetingSummary {
  return {
    external_id: 'ext-1',
    title: 'City Council',
    meeting_datetime: null,
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
  vi.mocked(getJsPortalPosture).mockResolvedValue({
    installed: false,
    detail: 'crawl4ai is not installed. Install civiccast[agenda-js-import].',
  })
  vi.mocked(listExternalAgendaMeetings).mockResolvedValue([externalMeeting()])
  vi.mocked(importExternalAgenda).mockResolvedValue([
    item({ item_id: 'item-ext-01', order: 0, confidence: 0.85 }),
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
      await findByText(/No agendas yet\./i),
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
      expect(vi.mocked(importAgendaFromDoc)).toHaveBeenCalledWith(
        'council-2026-01',
        pasted,
        'text/plain',
      ),
    )
    expect(await findByText(/Imported 2 items\./i)).toBeTruthy()
  })

  it('renders the unsupported-format message when the server returns 415', async () => {
    vi.mocked(importAgendaFromDoc).mockRejectedValue(
      new ApiError('Request failed: 415', 415, 'DOCX not supported.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Plain-text agenda to import'), {
      target: { value: 'anything' },
    })
    fireEvent.click(await findByRole('button', { name: /import agenda items from pasted text/i }))
    expect(
      await findByText(
        /Only plain-text and PDF agendas import here today \(DOCX and other formats are a follow-up\)\./i,
      ),
    ).toBeTruthy()
  })

  it('uploads a PDF file with contentType application/pdf and shows a low-confidence review banner', async () => {
    vi.mocked(importAgendaFromDoc).mockResolvedValue([
      item({ item_id: 'item-pdf-01', order: 0, confidence: 0.55 }),
    ])
    const { findByLabelText, findByRole, findByText } = renderScreen()
    const file = new File(['%PDF-1.4 fake'], 'agenda.pdf', { type: 'application/pdf' })
    const input = (await findByLabelText('PDF agenda to import')) as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(await findByRole('button', { name: /import agenda items from uploaded pdf/i }))
    await waitFor(() =>
      expect(vi.mocked(importAgendaFromDoc)).toHaveBeenCalledWith(
        'council-2026-01',
        file,
        'application/pdf',
      ),
    )
    expect(
      await findByText(/best-effort guess.*review them before publishing/i),
    ).toBeTruthy()
  })

  it('renders the could-not-find-items message when the server returns 422', async () => {
    vi.mocked(importAgendaFromDoc).mockRejectedValue(
      new ApiError('Request failed: 422', 422, 'No recognizable agenda items were found.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    const file = new File(['%PDF-1.4 fake'], 'agenda.pdf', { type: 'application/pdf' })
    const input = (await findByLabelText('PDF agenda to import')) as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(await findByRole('button', { name: /import agenda items from uploaded pdf/i }))
    expect(
      await findByText(/No recognizable agenda items were found\./i),
    ).toBeTruthy()
  })
})

describe('AgendasScreen external agenda import (Agenda Bridge)', () => {
  it('defaults to legistar and shows a tenant/site code field, no portal fields', async () => {
    const { findByLabelText, queryByLabelText } = renderScreen()
    const select = (await findByLabelText('External agenda source')) as HTMLSelectElement
    expect(select.value).toBe('legistar')
    expect(await findByLabelText('Tenant / site code')).toBeTruthy()
    expect(queryByLabelText('Portal URL')).toBeNull()
    expect(queryByLabelText('Vendor hint')).toBeNull()
  })

  it('selecting js_portal reveals the portal fields and checks runtime posture', async () => {
    const { findByLabelText } = renderScreen()
    const select = (await findByLabelText('External agenda source')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'js_portal' } })

    expect(await findByLabelText('Portal URL')).toBeTruthy()
    expect(await findByLabelText('Vendor hint')).toBeTruthy()
    await waitFor(() => expect(vi.mocked(getJsPortalPosture)).toHaveBeenCalled())
  })

  it('shows an honest not-installed state when the runtime posture reports installed:false', async () => {
    vi.mocked(getJsPortalPosture).mockResolvedValue({
      installed: false,
      detail: 'crawl4ai is not installed. Install civiccast[agenda-js-import].',
    })
    const { findByLabelText, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('External agenda source'), {
      target: { value: 'js_portal' },
    })

    expect(
      await findByText(/JS-portal runtime: not installed.*agenda-js-import/i),
    ).toBeTruthy()
  })

  it('shows the installed state once the posture query resolves installed:true', async () => {
    vi.mocked(getJsPortalPosture).mockResolvedValue({ installed: true, detail: 'ok' })
    const { findByLabelText, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('External agenda source'), {
      target: { value: 'js_portal' },
    })

    expect(await findByText('JS-portal runtime: installed.')).toBeTruthy()
  })

  it('shows a loading state for the posture check before it resolves', async () => {
    let resolvePosture: (v: { installed: boolean; detail: string }) => void = () => {}
    vi.mocked(getJsPortalPosture).mockReturnValue(
      new Promise((resolve) => {
        resolvePosture = resolve
      }),
    )
    const { findByLabelText, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('External agenda source'), {
      target: { value: 'js_portal' },
    })

    expect(await findByText(/Checking whether the JS-portal runtime is installed/i)).toBeTruthy()
    resolvePosture({ installed: true, detail: 'ok' })
    expect(await findByText('JS-portal runtime: installed.')).toBeTruthy()
  })

  it('finds meetings and lets the operator pick one', async () => {
    vi.mocked(listExternalAgendaMeetings).mockResolvedValue([
      externalMeeting({ external_id: 'ext-1', title: 'City Council' }),
      externalMeeting({ external_id: 'ext-2', title: 'Planning Commission' }),
    ])
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))

    await waitFor(() =>
      expect(vi.mocked(listExternalAgendaMeetings)).toHaveBeenCalledWith('legistar', 'seattle', {
        since: null,
        portalUrl: null,
        portalVendorHint: null,
      }),
    )
    const meetingSelect = (await findByLabelText('Meeting to import')) as HTMLSelectElement
    expect(meetingSelect.options.length).toBe(2)
  })

  it('shows the empty-results state when discovery finds nothing', async () => {
    vi.mocked(listExternalAgendaMeetings).mockResolvedValue([])
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))

    expect(await findByText('No meetings found for those filters.')).toBeTruthy()
  })

  it('surfaces a warn banner when discovery fails', async () => {
    vi.mocked(listExternalAgendaMeetings).mockRejectedValue(
      new ApiError('Request failed: 502', 502, 'PrimeGov request timed out.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))

    expect(await findByText('PrimeGov request timed out.')).toBeTruthy()
  })

  it('surfaces a distinct message when discovery 503s despite a healthy posture check', async () => {
    // Edge case, not a contradiction: describe_js_portal_runtime() only
    // proves crawl4ai is importable, not that the Playwright Chromium
    // binary is staged (js_portal.py's own docstring) -- a station can look
    // "installed" and still 503 at request time. Posture reports installed
    // so the Find Meetings button is enabled, and the server-side call
    // itself is what fails here.
    vi.mocked(getJsPortalPosture).mockResolvedValue({ installed: true, detail: 'ok' })
    vi.mocked(listExternalAgendaMeetings).mockRejectedValue(
      new ApiError('Request failed: 503', 503, 'crawl4ai is not installed.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('External agenda source'), {
      target: { value: 'js_portal' },
    })
    fireEvent.change(await findByLabelText('Portal URL'), {
      target: { value: 'https://fairview.example.gov/AgendaCenter' },
    })
    fireEvent.change(await findByLabelText('Display label'), {
      target: { value: 'fairview' },
    })
    await findByText('JS-portal runtime: installed.')
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))

    expect(await findByText('crawl4ai is not installed.')).toBeTruthy()
  })

  it('disables Find Meetings for js_portal when the posture check reports not installed', async () => {
    vi.mocked(getJsPortalPosture).mockResolvedValue({
      installed: false,
      detail: 'crawl4ai is not installed. Install civiccast[agenda-js-import].',
    })
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText('External agenda source'), {
      target: { value: 'js_portal' },
    })
    fireEvent.change(await findByLabelText('Portal URL'), {
      target: { value: 'https://fairview.example.gov/AgendaCenter' },
    })
    fireEvent.change(await findByLabelText('Display label'), {
      target: { value: 'fairview' },
    })

    const findButton = (await findByRole('button', {
      name: /find meetings/i,
    })) as HTMLButtonElement
    await waitFor(() => expect(findButton.disabled).toBe(true))
    expect(vi.mocked(listExternalAgendaMeetings)).not.toHaveBeenCalled()
  })

  it('imports the selected meeting and shows a success banner', async () => {
    vi.mocked(importExternalAgenda).mockResolvedValue([
      item({ item_id: 'item-ext-01', order: 0, confidence: 0.95 }),
    ])
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))
    await findByLabelText('Meeting to import')
    fireEvent.click(await findByRole('button', { name: /import the selected meeting/i }))

    await waitFor(() =>
      expect(vi.mocked(importExternalAgenda)).toHaveBeenCalledWith('council-2026-01', {
        source: 'legistar',
        client_code: 'seattle',
        event_id: 'ext-1',
        portal_url: null,
        portal_vendor_hint: null,
      }),
    )
    expect(await findByText('Imported 1 item.')).toBeTruthy()
  })

  it('flags low-confidence imported items for review', async () => {
    vi.mocked(importExternalAgenda).mockResolvedValue([
      item({ item_id: 'item-ext-01', order: 0, confidence: 0.4 }),
    ])
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))
    await findByLabelText('Meeting to import')
    fireEvent.click(await findByRole('button', { name: /import the selected meeting/i }))

    expect(
      await findByText(/lower confidence score.*review them before publishing/i),
    ).toBeTruthy()
  })

  it('surfaces a distinct message when import 503s (optional runtime not installed)', async () => {
    vi.mocked(importExternalAgenda).mockRejectedValue(
      new ApiError('Request failed: 503', 503, 'crawl4ai is not installed.'),
    )
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))
    await findByLabelText('Meeting to import')
    fireEvent.click(await findByRole('button', { name: /import the selected meeting/i }))

    expect(await findByText('crawl4ai is not installed.')).toBeTruthy()
  })

  it('warns that importing into a published agenda will move it back to draft', async () => {
    vi.mocked(listMeetingAgendas).mockResolvedValue([agenda({ status: 'published' })])
    vi.mocked(listAgendaItems).mockResolvedValue([item()])
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText('Tenant / site code'), {
      target: { value: 'seattle' },
    })
    fireEvent.click(await findByRole('button', { name: /find meetings/i }))
    await findByLabelText('Meeting to import')

    expect(
      await findByText(/This agenda is published\. Importing will move it back to draft/i),
    ).toBeTruthy()
  })
})

// WP-11 item 3 (owner directive): a regression test so the working
// CivicClerk/Legistar/PrimeGov agenda importer and the not-yet-built
// CivicSuite event bridge are never conflated on this screen.
describe('AgendasScreen CivicSuite bridge card', () => {
  it('shows the CivicSuite bridge as a future-release card beside the working importer, with no configuration fields', async () => {
    const { findByLabelText, findByText, queryByRole } = renderScreen()

    // The real importer is still present, selectable, and includes civicclerk.
    const source = (await findByLabelText('External agenda source')) as HTMLSelectElement
    const optionValues = Array.from(source.options).map((o) => o.value)
    expect(optionValues).toContain('civicclerk')

    // The future card is present, named distinctly, and explicit that it's
    // not built yet.
    expect(
      await findByText(/CivicSuite event bridge — coming in a future release/i),
    ).toBeTruthy()
    expect(
      await findByText(/authenticated connection to a jurisdiction.s CivicSuite account/i),
    ).toBeTruthy()
    expect(await findByText(/send published recording links back to CivicClerk/i)).toBeTruthy()

    // No executable configuration for the future bridge: nothing named
    // "CivicSuite" is an actual form control an operator could fill in.
    expect(queryByRole('button', { name: /civicsuite/i })).toBeNull()
    expect(queryByRole('textbox', { name: /civicsuite/i })).toBeNull()
    expect(queryByRole('combobox', { name: /civicsuite/i })).toBeNull()
  })

  it('keeps the working importer heading distinct from the future-bridge heading', async () => {
    const { findByText } = renderScreen()
    // Both headings render, and neither absorbed the other's copy: the
    // working importer's own heading says nothing about CivicSuite, and the
    // future card's heading says nothing about the working import flow.
    const importerHeading = await findByText('Import from an external agenda system')
    expect(importerHeading.textContent).not.toMatch(/CivicSuite/i)
    const bridgeHeading = await findByText(/CivicSuite event bridge — coming in a future release/i)
    expect(bridgeHeading.textContent).not.toMatch(/Import from an external agenda system/i)
  })
})
