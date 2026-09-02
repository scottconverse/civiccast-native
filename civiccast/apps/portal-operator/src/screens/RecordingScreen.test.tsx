// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  RecordingInputPreset,
  RecordingJob,
  RecordingJobState,
  RecordingSchedule,
} from '../api/client'
import type { StaffIdentityResponse } from '../types/api.generated'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
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
  getStaffIdentity: vi.fn(),
  listRecordingSchedules: vi.fn(),
  createRecordingSchedule: vi.fn(),
  updateRecordingSchedule: vi.fn(),
  deleteRecordingSchedule: vi.fn(),
  recordNow: vi.fn(),
  listRecordingJobs: vi.fn(),
  listRecordingInputPresets: vi.fn(),
  stopRecordingJob: vi.fn(),
}))

import {
  ApiError,
  createRecordingSchedule,
  deleteRecordingSchedule,
  getStaffIdentity,
  listRecordingJobs,
  listRecordingInputPresets,
  listRecordingSchedules,
  recordNow,
  stopRecordingJob,
  updateRecordingSchedule,
} from '../api/client'
import { RecordingScreen } from './RecordingScreen'
import {
  formatDurationHMS,
  humanizeBytes,
  humanizeRecurrence,
  humanizeSource,
  parseDurationHMS,
} from './recording-format'

function identity(roles: string[]): StaffIdentityResponse {
  return {
    operator_id: 'op',
    operator_display_name: 'Op',
    roles,
  } as StaffIdentityResponse
}

function schedule(overrides: Partial<RecordingSchedule> = {}): RecordingSchedule {
  const now = '2026-06-18T12:00:00Z'
  return {
    schedule_id: 'evening-news',
    station_id: 'civiccast-station',
    name: 'Evening News',
    source: { kind: 'sdi', input_id: 'sdi-1' },
    recurrence: { kind: 'weekly', weekdays: [0, 2], time_hhmm: '19:00' },
    duration_seconds: 3600,
    encoder_profile: 'default',
    loudness_regime: 'atsc-a85',
    target_series: null,
    custom_field_values: {},
    enabled: true,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

function job(overrides: Partial<RecordingJob> = {}): RecordingJob {
  const now = '2026-06-18T12:00:00Z'
  return {
    job_id: 'job-1',
    station_id: 'civiccast-station',
    schedule_id: 'evening-news',
    planned_start: '2026-06-18T19:00:00Z',
    planned_end: '2026-06-18T20:00:00Z',
    state: 'done',
    started_at: '2026-06-18T19:00:05Z',
    ended_at: '2026-06-18T20:00:00Z',
    asset_id: 'asset-2026-06-18',
    bytes_written: 1_200_000_000,
    failure_reason: null,
    source_snapshot: { kind: 'sdi', input_id: 'sdi-1' },
    encoder_profile: 'default',
    loudness_regime: 'atsc-a85',
    target_series: null,
    custom_field_values: {},
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <RecordingScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
  vi.mocked(listRecordingSchedules).mockResolvedValue([])
  vi.mocked(listRecordingJobs).mockResolvedValue([])
  vi.mocked(listRecordingInputPresets).mockResolvedValue([
    {
      preset_id: 'sdi-1',
      label: 'DeckLink SDI 1',
      source_kind: 'sdi',
      backend: 'decklink',
      device_name: 'DeckLink SDI 4K',
      audio_device_name: null,
      format_code: null,
      origin: 'detected',
    } satisfies RecordingInputPreset,
  ])
  vi.mocked(createRecordingSchedule).mockImplementation(async (payload) =>
    schedule({
      schedule_id: payload.schedule_id,
      name: payload.name,
      source: payload.source,
      recurrence: payload.recurrence,
      duration_seconds: payload.duration_seconds,
      encoder_profile: payload.encoder_profile,
      loudness_regime: payload.loudness_regime,
      target_series: payload.target_series,
      enabled: payload.enabled,
    }),
  )
  vi.mocked(updateRecordingSchedule).mockImplementation(async (id, payload) =>
    schedule({
      schedule_id: id,
      name: payload.name ?? 'Evening News',
      enabled: payload.enabled ?? true,
    }),
  )
  vi.mocked(deleteRecordingSchedule).mockResolvedValue(undefined)
  vi.mocked(recordNow).mockImplementation(async () =>
    job({ state: 'arming', asset_id: null, bytes_written: 0 }),
  )
  vi.mocked(stopRecordingJob).mockImplementation(async (id) => job({ job_id: id, state: 'done' }))
})

// --- Pure formatter tests ---------------------------------------------------

describe('RecordingScreen formatters', () => {
  it('round-trips HH:MM:SS through parse + format', () => {
    expect(parseDurationHMS('01:30:00')).toBe(5400)
    expect(formatDurationHMS(5400)).toBe('01:30:00')
    expect(parseDurationHMS('00:00:30')).toBe(30)
    expect(formatDurationHMS(30)).toBe('00:00:30')
    expect(parseDurationHMS('12:34:56')).toBe(12 * 3600 + 34 * 60 + 56)
  })

  it('rejects bad duration input', () => {
    expect(parseDurationHMS('')).toBeNull()
    expect(parseDurationHMS('abc')).toBeNull()
    expect(parseDurationHMS('1:5:0')).toBeNull() // minute / second need two digits
    expect(parseDurationHMS('1:60:00')).toBeNull() // minute > 59
    expect(parseDurationHMS('1:00:60')).toBeNull() // second > 59
    expect(parseDurationHMS('00:00:00')).toBeNull() // zero rejected
  })

  it('humanizes SDI / RTSP sources', () => {
    expect(humanizeSource({ kind: 'sdi', input_id: 'sdi-1' })).toBe('SDI sdi-1')
    expect(humanizeSource({ kind: 'rtsp', uri: 'rtsp://camera.local/stream' })).toBe(
      'RTSP rtsp://camera.local/stream',
    )
  })

  it('humanizes one-shot and weekly recurrence', () => {
    expect(
      humanizeRecurrence({ kind: 'one_shot', start: '2026-06-20T19:00:00Z' }),
    ).toBe('One-shot 2026-06-20 19:00 UTC')
    expect(
      humanizeRecurrence({ kind: 'weekly', weekdays: [0, 2], time_hhmm: '19:00' }),
    ).toBe('Weekly Mon/Wed 19:00 UTC')
  })

  it('humanizes bytes with decimal SI shape', () => {
    expect(humanizeBytes(0)).toBe('0 B')
    expect(humanizeBytes(1_200_000_000)).toBe('1.2 GB')
    expect(humanizeBytes(850_000_000)).toBe('850.0 MB')
  })
})

// --- Role gate -------------------------------------------------------------

describe('RecordingScreen role gate', () => {
  it('shows Forbidden for a role outside view roles', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/Forbidden/i)).toBeTruthy()
    expect(vi.mocked(listRecordingSchedules)).not.toHaveBeenCalled()
  })

  it('renders the schedules table for support_admin read-only (no actions)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    const { findByText, queryByRole } = renderScreen()
    expect(await findByText('Evening News')).toBeTruthy()
    // No Record-now, Edit, Delete, or Create form for read-only.
    expect(queryByRole('button', { name: /Record now from/i })).toBeNull()
    expect(queryByRole('button', { name: /Edit schedule/i })).toBeNull()
    expect(queryByRole('button', { name: /Delete schedule/i })).toBeNull()
    expect(queryByRole('button', { name: /Create schedule/i })).toBeNull()
  })

  it('renders the action buttons for setup_admin', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    const { findByRole } = renderScreen()
    expect(await findByRole('button', { name: /Record now from Evening News/i })).toBeTruthy()
    expect(await findByRole('button', { name: /Edit schedule Evening News/i })).toBeTruthy()
    expect(await findByRole('button', { name: /Delete schedule Evening News/i })).toBeTruthy()
  })

  it('renders the action buttons for meeting_operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    const { findByRole } = renderScreen()
    expect(await findByRole('button', { name: /Record now from Evening News/i })).toBeTruthy()
    expect(await findByRole('button', { name: /Delete schedule Evening News/i })).toBeTruthy()
  })
})

// --- Empty states ---------------------------------------------------------

describe('RecordingScreen empty states', () => {
  it('shows the schedules empty-state copy when no schedules', async () => {
    const { findByText } = renderScreen()
    expect(
      await findByText(/No recording schedules yet\./i),
    ).toBeTruthy()
  })

  it('shows the recordings empty-state copy when no recordings', async () => {
    const { findByText } = renderScreen()
    expect(
      await findByText(/No recordings yet\./i),
    ).toBeTruthy()
  })
})

// --- Form validation ------------------------------------------------------

describe('RecordingScreen form validation', () => {
  it('flags missing URI on a network-stream source', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'late-news' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'rtsp' } })
    // intentionally leave URI blank
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(await findByText(/URI is required for network streams/i)).toBeTruthy()
    expect(vi.mocked(createRecordingSchedule)).not.toHaveBeenCalled()
  })

  it('flags weekly with no weekdays selected', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'late-news' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'sdi' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Recurrence/i), { target: { value: 'weekly' } })
    // Don't tick any weekdays. Set a valid time so only the weekdays-error surfaces.
    fireEvent.change(await findByLabelText(/Time \(HH:MM UTC\)/i), {
      target: { value: '19:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(await findByText(/Pick at least one weekday/i)).toBeTruthy()
    expect(vi.mocked(createRecordingSchedule)).not.toHaveBeenCalled()
  })

  it('flags one_shot with missing start', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'late-news' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(await findByText(/Start time is required/i)).toBeTruthy()
    expect(vi.mocked(createRecordingSchedule)).not.toHaveBeenCalled()
  })

  it('flags bad HH:MM:SS duration on submit', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'late-news' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.change(await findByLabelText(/Duration \(HH:MM:SS\)/i), {
      target: { value: 'not-a-duration' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(
      await findByText(/Duration must be HH:MM:SS/i),
    ).toBeTruthy()
    expect(vi.mocked(createRecordingSchedule)).not.toHaveBeenCalled()
  })

  it('creates a schedule with the parsed duration in seconds', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'late-news' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.change(await findByLabelText(/Duration \(HH:MM:SS\)/i), {
      target: { value: '01:30:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    await waitFor(() =>
      expect(vi.mocked(createRecordingSchedule)).toHaveBeenCalledWith(
        expect.objectContaining({
          schedule_id: 'late-news',
          duration_seconds: 5400,
          source: { kind: 'sdi', input_id: 'sdi-1' },
          recurrence: { kind: 'one_shot', start: '2026-06-20T19:00:00Z' },
          enabled: true,
        }),
      ),
    )
  })
})

// --- Screen-reader-oriented validation wiring (WP-11 item 1) ---------------
//
// Every validation message needs a stable id; the offending control (or
// group) needs aria-invalid + aria-describedby pointing at that id; and a
// failed submit must move keyboard/screen-reader focus to the FIRST invalid
// control, not just the form heading. These assertions read the real DOM
// attributes rather than only the visible copy, so a regression that drops
// the wiring (but leaves the message text in place) still fails here.

describe('RecordingScreen validation accessibility wiring', () => {
  it('focuses the slug field and wires aria-invalid/aria-describedby on an empty submit', async () => {
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    const slug = (await findByLabelText(/Schedule ID \(slug\)/i)) as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(slug))
    expect(slug.getAttribute('aria-invalid')).toBe('true')

    const describedBy = slug.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    const message = document.getElementById(describedBy as string)
    expect(message).toBeTruthy()
    expect(message?.getAttribute('role')).toBe('alert')
    expect(message?.textContent).toMatch(/Slug required/i)
  })

  it('focuses the Name field (not the slug field) when only Name is invalid', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    // Grab the Name field handle before any error renders: once the error
    // span mounts inside the same <label>, the label's accessible name is
    // "Name" + the error text concatenated, so an exact-match query against
    // it after submission is unreliable. The element identity is stable
    // across the state update (React doesn't remount it), so the handle
    // grabbed now stays valid for the assertions below.
    const name = (await findByLabelText(/^Name$/i)) as HTMLInputElement
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    await waitFor(() => expect(document.activeElement).toBe(name))
    expect(name.getAttribute('aria-invalid')).toBe('true')
    const describedBy = name.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy as string)?.textContent).toMatch(
      /Name is required/i,
    )
  })

  it('focuses the URI field and marks it invalid when a network source is missing its URI', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'rtsp' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    const uri = (await findByLabelText(/^URI$/i)) as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(uri))
    expect(uri.getAttribute('aria-invalid')).toBe('true')
    const describedBy = uri.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy as string)?.textContent).toMatch(
      /URI is required/i,
    )
  })

  it('focuses the first weekday checkbox and marks the Weekdays group invalid when none is checked', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Recurrence/i), { target: { value: 'weekly' } })
    // Don't tick any weekdays. Set a valid time so only the weekdays-error surfaces.
    fireEvent.change(await findByLabelText(/Time \(HH:MM UTC\)/i), {
      target: { value: '19:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    const mondayCheckbox = (await findByLabelText(/Weekly day Mon/i)) as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(mondayCheckbox))

    const group = await findByRole('group', { name: /Weekdays/i })
    expect(group.getAttribute('aria-invalid')).toBe('true')
    const describedBy = group.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    const message = document.getElementById(describedBy as string)
    expect(message?.getAttribute('role')).toBe('alert')
    expect(message?.textContent).toMatch(/Pick at least one weekday/i)
  })

  it('focuses the weekly time field and marks it invalid when the time format is bad', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Recurrence/i), { target: { value: 'weekly' } })
    fireEvent.click(await findByLabelText(/Weekly day Mon/i))
    fireEvent.change(await findByLabelText(/Time \(HH:MM UTC\)/i), {
      target: { value: 'not-a-time' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    const time = (await findByLabelText(/Time \(HH:MM UTC\)/i)) as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(time))
    expect(time.getAttribute('aria-invalid')).toBe('true')
    const describedBy = time.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy as string)?.textContent).toMatch(
      /Time must be HH:MM/i,
    )
  })

  it('focuses the duration field when it is the only invalid field', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.change(await findByLabelText(/Duration \(HH:MM:SS\)/i), {
      target: { value: 'not-a-duration' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    const duration = (await findByLabelText(/Duration \(HH:MM:SS\)/i)) as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(duration))
    expect(duration.getAttribute('aria-invalid')).toBe('true')
    const describedBy = duration.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy as string)?.textContent).toMatch(
      /Duration must be HH:MM:SS/i,
    )
  })

  it('clears aria-invalid once the field is corrected and resubmitted successfully', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    // Grab every handle before the first (all-fields-empty) submit: once
    // errors render inside these labels, exact-match label queries against
    // them become unreliable (see the Name-field test above). Element
    // identity survives the state update, so the handles stay valid.
    const slug = (await findByLabelText(/Schedule ID \(slug\)/i)) as HTMLInputElement
    const name = (await findByLabelText(/^Name$/i)) as HTMLInputElement
    const inputId = (await findByLabelText(/Input ID/i)) as HTMLInputElement
    const start = (await findByLabelText(/Start \(UTC\)/i)) as HTMLInputElement

    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(slug.getAttribute('aria-invalid')).toBe('true')

    fireEvent.change(slug, { target: { value: 'late-news' } })
    fireEvent.change(name, { target: { value: 'Late News' } })
    fireEvent.change(inputId, { target: { value: 'sdi-1' } })
    fireEvent.change(start, { target: { value: '2026-06-20T19:00' } })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))

    await waitFor(() => expect(vi.mocked(createRecordingSchedule)).toHaveBeenCalled())
    expect(slug.getAttribute('aria-invalid')).toBeNull()
    expect(slug.getAttribute('aria-describedby')).toBeNull()
  })
})

// --- 2-step delete confirm --------------------------------------------------

describe('RecordingScreen delete confirm', () => {
  it('does not delete on the first click, deletes on the second', async () => {
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /Delete schedule Evening News/i }))
    expect(vi.mocked(deleteRecordingSchedule)).not.toHaveBeenCalled()
    fireEvent.click(
      await findByRole('button', { name: /Confirm delete schedule Evening News/i }),
    )
    await waitFor(() =>
      expect(vi.mocked(deleteRecordingSchedule)).toHaveBeenCalledWith('evening-news'),
    )
  })
})

// --- Record-now ------------------------------------------------------------

describe('RecordingScreen record-now', () => {
  it('POSTs /record-now and refreshes jobs on success', async () => {
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    const { findByRole } = renderScreen()
    fireEvent.click(
      await findByRole('button', { name: /Record now from Evening News/i }),
    )
    await waitFor(() =>
      expect(vi.mocked(recordNow)).toHaveBeenCalledWith('evening-news'),
    )
    await waitFor(() =>
      expect(vi.mocked(listRecordingJobs)).toHaveBeenCalledTimes(2),
    )
  })

  it('surfaces the degraded-mode banner on 503', async () => {
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    vi.mocked(recordNow).mockRejectedValueOnce(
      new ApiError('Runtime unavailable', 503, 'runtime unavailable'),
    )
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(
      await findByRole('button', { name: /Record now from Evening News/i }),
    )
    expect(
      await findByText(/Scheduled recording runtime is unavailable in this deployment/i),
    ).toBeTruthy()
  })

  it('disables Record now once the 503 banner is up', async () => {
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    vi.mocked(recordNow).mockRejectedValueOnce(
      new ApiError('Runtime unavailable', 503, 'runtime unavailable'),
    )
    const { findByRole, findByText } = renderScreen()
    const btn = (await findByRole('button', {
      name: /Record now from Evening News/i,
    })) as HTMLButtonElement
    fireEvent.click(btn)
    await findByText(/Scheduled recording runtime is unavailable/i)
    const btnAfter = (await findByRole('button', {
      name: /Record now from Evening News/i,
    })) as HTMLButtonElement
    expect(btnAfter.disabled).toBe(true)
  })
})

// --- State badge ----------------------------------------------------------

describe('RecordingScreen state badge', () => {
  it('renders each of the 7 job states with a color-coded badge', async () => {
    const states: RecordingJobState[] = [
      'scheduled',
      'arming',
      'recording',
      'finalizing',
      'done',
      'failed',
      'skipped',
    ]
    vi.mocked(listRecordingJobs).mockResolvedValue(
      states.map((s, i) =>
        job({ job_id: `job-${i}`, state: s, asset_id: null, bytes_written: 0 }),
      ),
    )
    const { findByTestId } = renderScreen()
    for (const s of states) {
      expect(await findByTestId(`job-state-badge-${s}`)).toBeTruthy()
    }
  })
})

// --- Auto-refresh --------------------------------------------------------

describe('RecordingScreen jobs auto-refresh', () => {
  it('polls listRecordingJobs while an active job is present', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(listRecordingJobs).mockResolvedValue([job({ state: 'recording' })])
    const { findByText } = renderScreen()
    // Wait for the initial render to settle (one fetch has fired).
    await findByText(/Evening News/i).catch(() => null)
    await waitFor(() => expect(vi.mocked(listRecordingJobs)).toHaveBeenCalledTimes(1))
    const before = vi.mocked(listRecordingJobs).mock.calls.length
    await act(async () => {
      vi.advanceTimersByTime(5100)
    })
    await waitFor(() =>
      expect(vi.mocked(listRecordingJobs).mock.calls.length).toBeGreaterThan(before),
    )
  })
})

// --- Stop action ---------------------------------------------------------

describe('RecordingScreen stop active job', () => {
  // UX-1: Stop is a 2-step confirm so a misclick mid-meeting can't kill a
  // live recording. The first click arms; the second click stops.
  it('does NOT call the API on the first Stop click', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([
      job({ job_id: 'job-active', state: 'recording', asset_id: null, bytes_written: 0 }),
    ])
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^Stop job job-active$/i }))
    // Give react-query a tick to flush — if the API were called it'd be by
    // now. Confirm-stop button appears in the DOM.
    expect(await findByRole('button', { name: /Confirm stop job job-active/i })).toBeTruthy()
    expect(vi.mocked(stopRecordingJob)).not.toHaveBeenCalled()
  })

  it('calls POST /jobs/{id}/stop only after Confirm stop is clicked', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([
      job({ job_id: 'job-active', state: 'recording', asset_id: null, bytes_written: 0 }),
    ])
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^Stop job job-active$/i }))
    fireEvent.click(await findByRole('button', { name: /Confirm stop job job-active/i }))
    await waitFor(() =>
      expect(vi.mocked(stopRecordingJob)).toHaveBeenCalledWith('job-active'),
    )
  })

  it('Cancel stop disarms the confirm without calling the API', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([
      job({ job_id: 'job-active', state: 'recording', asset_id: null, bytes_written: 0 }),
    ])
    const { findByRole, queryByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /^Stop job job-active$/i }))
    fireEvent.click(await findByRole('button', { name: /Cancel stop job job-active/i }))
    expect(vi.mocked(stopRecordingJob)).not.toHaveBeenCalled()
    // Back to single Stop button; no confirm in the DOM.
    expect(queryByRole('button', { name: /Confirm stop job job-active/i })).toBeNull()
    expect(await findByRole('button', { name: /^Stop job job-active$/i })).toBeTruthy()
  })

  it('omits the Stop button for terminal-state jobs', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([
      job({ job_id: 'job-done', state: 'done' }),
    ])
    const { findByText, queryByRole } = renderScreen()
    await findByText(/asset-2026-06-18/)
    expect(queryByRole('button', { name: /Stop job job-done/i })).toBeNull()
  })
})

// --- UX lock-in tests ------------------------------------------------------
//
// These tests pin the audit-deep-dive findings closed — if a future refactor
// regresses one, the test for the specific UX-id flags it.

describe('RecordingScreen UX-2 timezone honesty', () => {
  it('renders a live local-time echo under the one-shot Start (UTC) input', async () => {
    const { findByLabelText, findByTestId } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    const echo = await findByTestId('one-shot-local-echo')
    // The echo always starts with the "In your local time:" preamble; we
    // don't pin the exact zone because vitest's TZ floats by host.
    expect(echo.textContent ?? '').toMatch(/In your local time:/)
    // It must NOT just be the dash placeholder.
    expect(echo.textContent ?? '').not.toMatch(/In your local time:\s*—\s*$/)
  })

  it('renders a live local-time echo under the weekly HH:MM UTC input', async () => {
    const { findByLabelText, findByTestId } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/Recurrence/i), {
      target: { value: 'weekly' },
    })
    fireEvent.change(await findByLabelText(/Time \(HH:MM UTC\)/i), {
      target: { value: '19:00' },
    })
    const echo = await findByTestId('weekly-time-local-echo')
    expect(echo.textContent ?? '').toMatch(/In your local time:/)
  })

  it('UTC datetime-local submits with the correct :00Z suffix', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-07-04T19:00' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    await waitFor(() =>
      expect(vi.mocked(createRecordingSchedule)).toHaveBeenCalledWith(
        expect.objectContaining({
          recurrence: { kind: 'one_shot', start: '2026-07-04T19:00:00Z' },
        }),
      ),
    )
  })
})

describe('RecordingScreen UX-8 next-fire preview', () => {
  it('shows a Next-fires preview block for a weekly Mon/Wed schedule', async () => {
    const { findByLabelText, findByTestId, getAllByLabelText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/Recurrence/i), {
      target: { value: 'weekly' },
    })
    // Tick Mon + Wed.
    const monBox = getAllByLabelText(/Weekly day Mon/i)[0]
    const wedBox = getAllByLabelText(/Weekly day Wed/i)[0]
    fireEvent.click(monBox)
    fireEvent.click(wedBox)
    fireEvent.change(await findByLabelText(/Time \(HH:MM UTC\)/i), {
      target: { value: '19:00' },
    })
    const preview = await findByTestId('next-fire-preview')
    expect(preview.textContent ?? '').toMatch(/Next 3 fires/)
    // The block lists three dates; each line has " UTC" + a local echo.
    expect((preview.querySelectorAll('li') ?? []).length).toBe(3)
  })

  it('shows a single Next fire preview for a one-shot schedule', async () => {
    const { findByLabelText, findByTestId } = renderScreen()
    // Pick a date safely in the future so the preview isn't filtered out.
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2099-01-15T18:30' },
    })
    const preview = await findByTestId('next-fire-preview')
    expect(preview.textContent ?? '').toMatch(/Next fire/)
    expect(preview.querySelectorAll('li').length).toBe(1)
  })
})

describe('RecordingScreen UX-3 encoder profile discoverability', () => {
  it('exposes a <datalist> of encoder-profile suggestions for the input', async () => {
    const { findByLabelText, container } = renderScreen()
    const input = (await findByLabelText(
      /Quality preset \(encoder profile\)/i,
    )) as HTMLInputElement
    expect(input.getAttribute('list')).toBeTruthy()
    const listId = input.getAttribute('list')!
    // CSS.escape isn't in the jsdom global; do a plain getElementById here.
    // useId() returns ids of the form ":r5:" which getElementById accepts.
    const datalist = container.querySelector(`datalist[id="${listId}"]`)
    expect(datalist).toBeTruthy()
    expect(datalist?.tagName.toLowerCase()).toBe('datalist')
    const opts = Array.from(datalist?.querySelectorAll('option') ?? []).map(
      (o) => (o as HTMLOptionElement).value,
    )
    // The seed list documented in the screen source.
    expect(opts).toContain('h264-1080p')
    expect(opts).toContain('h264-720p')
    expect(opts).toContain('hw-h264-1080p')
    expect(opts).toContain('hw-h264-720p')
    expect(opts).not.toContain('cable-mpeg2-1080i')
    expect(opts).not.toContain('sw-h264-1080p')
  })

  it('shows inline help text for the encoder profile field', async () => {
    const { findByText } = renderScreen()
    expect(
      await findByText(/Common values:.*hw-h264-1080p/i),
    ).toBeTruthy()
  })
})

describe('RecordingScreen UX-4 loudness regime help', () => {
  it('updates inline help text when the loudness regime changes', async () => {
    const { findByLabelText, findByTestId } = renderScreen()
    fireEvent.change(await findByLabelText(/Loudness regime/i), {
      target: { value: 'atsc-a85' },
    })
    const help = await findByTestId('loudness-help')
    expect(help.textContent ?? '').toMatch(/ATSC A\/85/i)
    fireEvent.change(await findByLabelText(/Loudness regime/i), {
      target: { value: 'ebu-r128' },
    })
    expect((await findByTestId('loudness-help')).textContent ?? '').toMatch(
      /EBU R128/i,
    )
  })
})

describe('RecordingScreen UX-5 source kind optgroups', () => {
  it('groups source kinds into Live inputs and Network streams', async () => {
    const { findByLabelText } = renderScreen()
    const select = (await findByLabelText(/Source kind/i)) as HTMLSelectElement
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) =>
      g.getAttribute('label'),
    )
    expect(groups).toEqual(['Live inputs', 'Network streams'])
  })
})

describe('RecordingScreen capture-card presets', () => {
  it('shows only presets for the selected SDI or HDMI source kind', async () => {
    vi.mocked(listRecordingInputPresets).mockResolvedValue([
      {
        preset_id: 'decklink-2', label: 'DeckLink channel 2', source_kind: 'sdi',
        backend: 'decklink', device_name: 'DeckLink Duo 2 (2)', audio_device_name: null,
        format_code: 'Hp60', origin: 'configured',
      },
      {
        preset_id: 'cam-link', label: 'Cam Link HDMI', source_kind: 'hdmi',
        backend: 'dshow', device_name: 'Cam Link HDMI', audio_device_name: null,
        format_code: null, origin: 'detected',
      },
    ])
    const { findByLabelText, findByRole, queryByRole } = renderScreen()
    const input = await findByLabelText(/Input ID/i)
    expect(await findByRole('option', { name: /DeckLink channel 2/i })).toBeTruthy()
    expect(queryByRole('option', { name: /Cam Link HDMI/i })).toBeNull()

    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'hdmi' } })
    expect(queryByRole('option', { name: /DeckLink channel 2/i })).toBeNull()
    expect(queryByRole('option', { name: /Cam Link HDMI/i })).toBeTruthy()
    expect(input.tagName).toBe('SELECT')
  })

  it('clears a chosen SDI preset when the source kind switches to HDMI', async () => {
    vi.mocked(listRecordingInputPresets).mockResolvedValue([
      {
        preset_id: 'decklink-2', label: 'DeckLink channel 2', source_kind: 'sdi',
        backend: 'decklink', device_name: 'DeckLink Duo 2 (2)', audio_device_name: null,
        format_code: 'Hp60', origin: 'configured',
      },
      {
        preset_id: 'cam-link', label: 'Cam Link HDMI', source_kind: 'hdmi',
        backend: 'dshow', device_name: 'Cam Link HDMI', audio_device_name: null,
        format_code: null, origin: 'detected',
      },
    ])
    const { findByLabelText, findByRole, findByText, queryByText } = renderScreen()
    await findByRole('option', { name: /DeckLink channel 2/i })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'decklink-2' } })
    expect(((await findByLabelText(/Input ID/i)) as HTMLSelectElement).value).toBe('decklink-2')

    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'hdmi' } })
    const input = (await findByLabelText(/Input ID/i)) as HTMLSelectElement
    expect(input.value).toBe('')
    expect(queryByText(/Saved input unavailable/i)).toBeNull()

    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), { target: { value: 'hdmi-meeting' } })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'HDMI meeting' } })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(await findByText(/Input ID is required for live sources/i)).toBeTruthy()
    expect(createRecordingSchedule).not.toHaveBeenCalled()
  })

  it('fails visibly when no selected-kind capture input exists', async () => {
    vi.mocked(listRecordingInputPresets).mockResolvedValue([])
    const { findByLabelText, findByText } = renderScreen()
    const input = (await findByLabelText(/Input ID/i)) as HTMLSelectElement
    expect(input.disabled).toBe(true)
    expect(await findByText(/No SDI capture input was detected or configured/i)).toBeTruthy()
  })

  it('keeps NDI as a manually named network input', async () => {
    const { findByLabelText } = renderScreen()
    fireEvent.change(await findByLabelText(/Source kind/i), { target: { value: 'ndi' } })
    const input = (await findByLabelText(/Input ID/i)) as HTMLInputElement
    expect(input.tagName).toBe('INPUT')
    expect(input.placeholder).toBe('studio-ndi')
  })
})

describe('RecordingScreen UX-6 auto-refresh visibility', () => {
  it('shows the Live pill while an active job is present', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([job({ state: 'recording' })])
    const { findByTestId } = renderScreen()
    const pill = await findByTestId('autorefresh-pill')
    expect(pill.textContent ?? '').toMatch(/Live · refreshing every 5 s/i)
  })

  it('Pause toggles the pill to Paused and stops the poll', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(listRecordingJobs).mockResolvedValue([job({ state: 'recording' })])
    const { findByTestId, findByRole } = renderScreen()
    await findByTestId('autorefresh-pill')
    fireEvent.click(await findByRole('button', { name: /Pause auto-refresh/i }))
    expect((await findByTestId('autorefresh-pill')).textContent ?? '').toMatch(
      /Paused/i,
    )
    const before = vi.mocked(listRecordingJobs).mock.calls.length
    await act(async () => {
      vi.advanceTimersByTime(15000)
    })
    // Paused → no further polls.
    expect(vi.mocked(listRecordingJobs).mock.calls.length).toBe(before)
  })
})

describe('RecordingScreen UX-7 failure reason emphasis', () => {
  it('renders a failed-job failure_reason in error ink, not low-grey', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([
      job({
        job_id: 'job-failed',
        state: 'failed',
        failure_reason: 'unknown encoder profile',
        asset_id: null,
      }),
    ])
    const { findByText } = renderScreen()
    const cell = await findByText('unknown encoder profile')
    const td = cell.closest('td')!
    // Inline style sets color: var(--cc-err). We also want no text-stone-300.
    expect(td.style.color).toMatch(/var\(--cc-err\)/)
    expect(td.className).not.toMatch(/text-stone-300/)
  })
})

describe('RecordingScreen UX-9 duration error spells out the rule', () => {
  it('returns a specific message naming the two-digit minute/second rule', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.change(await findByLabelText(/Schedule ID \(slug\)/i), {
      target: { value: 'late-news' },
    })
    fireEvent.change(await findByLabelText(/^Name$/i), { target: { value: 'Late News' } })
    fireEvent.change(await findByLabelText(/Input ID/i), { target: { value: 'sdi-1' } })
    fireEvent.change(await findByLabelText(/Start \(UTC\)/i), {
      target: { value: '2026-06-20T19:00' },
    })
    fireEvent.change(await findByLabelText(/Duration \(HH:MM:SS\)/i), {
      target: { value: '1:5:0' },
    })
    fireEvent.click(await findByRole('button', { name: /Create schedule/i }))
    expect(
      await findByText(/minutes and seconds need two digits.*01:05:00.*1:5:0/i),
    ).toBeTruthy()
  })
})

describe('RecordingScreen UX-11 weekly day presets', () => {
  it('Weekdays preset selects Mon-Fri and clears Sat/Sun', async () => {
    const { findByLabelText, findByRole, getAllByLabelText } = renderScreen()
    fireEvent.change(await findByLabelText(/Recurrence/i), {
      target: { value: 'weekly' },
    })
    fireEvent.click(
      await findByRole('button', { name: /Weekly preset: weekdays/i }),
    )
    const checked = (label: RegExp) =>
      (getAllByLabelText(label)[0] as HTMLInputElement).checked
    expect(checked(/Weekly day Mon/i)).toBe(true)
    expect(checked(/Weekly day Fri/i)).toBe(true)
    expect(checked(/Weekly day Sat/i)).toBe(false)
    expect(checked(/Weekly day Sun/i)).toBe(false)
  })

  it('Clear preset unchecks every weekday', async () => {
    const { findByLabelText, findByRole, getAllByLabelText } = renderScreen()
    fireEvent.change(await findByLabelText(/Recurrence/i), {
      target: { value: 'weekly' },
    })
    fireEvent.click(
      await findByRole('button', { name: /Weekly preset: every day/i }),
    )
    fireEvent.click(
      await findByRole('button', { name: /Weekly preset: clear all days/i }),
    )
    for (const lbl of [/Mon/i, /Tue/i, /Wed/i, /Thu/i, /Fri/i, /Sat/i, /Sun/i]) {
      const re = new RegExp(`Weekly day ${lbl.source}`, 'i')
      expect((getAllByLabelText(re)[0] as HTMLInputElement).checked).toBe(false)
    }
  })
})

describe('RecordingScreen UX-12 / UX-13 operator vocabulary', () => {
  it('labels the encoder field "Quality preset"', async () => {
    const { findByLabelText } = renderScreen()
    expect(await findByLabelText(/Quality preset/i)).toBeTruthy()
  })

  it('labels the recordings table region "Recordings" not "Jobs"', async () => {
    const { findByRole } = renderScreen()
    expect(await findByRole('region', { name: /^Recordings$/i })).toBeTruthy()
  })
})

describe('RecordingScreen UX-16 Refresh busy state', () => {
  it('disables and relabels Refresh while a refetch is in flight', async () => {
    let resolveJobs: (v: RecordingJob[]) => void = () => {}
    vi.mocked(listRecordingJobs).mockImplementation(
      () =>
        new Promise<RecordingJob[]>((res) => {
          resolveJobs = res
        }),
    )
    const { findByRole } = renderScreen()
    const btn = (await findByRole('button', {
      name: /Refresh recordings/i,
    })) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.textContent).toMatch(/Refreshing…/)
    resolveJobs([])
    await waitFor(() => {
      const after = btn
      expect(after.disabled).toBe(false)
      expect(after.textContent).toMatch(/^Refresh$/)
    })
  })
})

describe('RecordingScreen UX-17 accessible table captions', () => {
  it('renders a screen-reader caption inside both tables', async () => {
    vi.mocked(listRecordingSchedules).mockResolvedValue([schedule()])
    vi.mocked(listRecordingJobs).mockResolvedValue([job()])
    const { findByText, container } = renderScreen()
    await findByText(/Evening News/)
    const captions = Array.from(container.querySelectorAll('caption')).map(
      (c) => c.textContent,
    )
    expect(captions).toEqual(
      expect.arrayContaining(['Recording schedules', 'Recordings']),
    )
  })
})

describe('RecordingScreen UX-18 asset link affordance', () => {
  it('opens completed recording assets inside the operator route', async () => {
    vi.mocked(listRecordingJobs).mockResolvedValue([job()])
    const { findByRole } = renderScreen()
    const link = await findByRole('link', { name: /asset-2026-06-18/i })
    expect(link.getAttribute('title')).toBe('asset-2026-06-18')
    expect(link.getAttribute('href')).toBe('#/assets/asset-2026-06-18')
  })
})
