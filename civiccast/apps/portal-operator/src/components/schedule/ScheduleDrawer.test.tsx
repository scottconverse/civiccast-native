// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// F-RC3-6 regression guard (clean-VM gauntlet, v1.0.0-rc3): the drawer's
// channel options MUST come from the station's real cable channels
// (/api/staff/cable/channels) — the ids the playout/commit-to-air lane keys
// on. rc3 shipped a hardcoded demo list (gov-ch12/edu-ch14), so programs
// scheduled through the UI landed on channel ids the commit panel could
// never see, severing schedule→air.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { AssetRow } from '../../types/asset'
import type { ChannelProfile } from '../../types/api.generated'

afterEach(cleanup)

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  createSchedule: vi.fn(),
  listChannelProfiles: vi.fn(),
  listStaffAssets: vi.fn(),
}))

import {
  createSchedule,
  listChannelProfiles,
  listStaffAssets,
} from '../../api/client'
import { ScheduleDrawer } from './ScheduleDrawer'

const channelProfile = (id: string, name: string): ChannelProfile =>
  ({
    channel_id: id,
    slug: id,
    kind: 'government',
    branding: {
      display_name: name,
      short_name: name,
      color: '#000000',
      logo_text: name.toUpperCase(),
    },
    fallback_behavior: 'slate',
  }) as ChannelProfile

const validatedAsset: AssetRow = {
  asset_id: 'asset-1',
  title: 'Sample rehearsal',
  state: 'validated',
} as AssetRow

function renderDrawer() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ScheduleDrawer onClose={() => {}} onCreated={() => {}} />
    </QueryClientProvider>,
  )
}

describe('ScheduleDrawer channel options (F-RC3-6)', () => {
  it('renders the station channels from the cable-channels API, not a hardcoded list', async () => {
    vi.mocked(listStaffAssets).mockResolvedValue([validatedAsset])
    vi.mocked(listChannelProfiles).mockResolvedValue([
      channelProfile('public', 'Public Channel'),
      channelProfile('government', 'Government Channel'),
    ])

    const view = renderDrawer()
    await waitFor(() => {
      expect(view.getByText('Public Channel')).toBeTruthy()
    })
    expect(view.getByText('Government Channel')).toBeTruthy()
    // The rc3 hardcoded demo entries must never come back.
    expect(view.queryByText('Gov · Channel 12')).toBeNull()
    expect(view.queryByText('Edu · Channel 14')).toBeNull()
  })

  it('submits the selected REAL channel id to createSchedule', async () => {
    vi.mocked(listStaffAssets).mockResolvedValue([validatedAsset])
    vi.mocked(listChannelProfiles).mockResolvedValue([
      channelProfile('public', 'Public Channel'),
      channelProfile('government', 'Government Channel'),
    ])
    vi.mocked(createSchedule).mockResolvedValue({
      item_id: 'sched-1',
      asset_id: 'asset-1',
      channel_id: 'government',
      mode: 'premiere',
      scheduled_at: new Date().toISOString(),
    } as never)

    const view = renderDrawer()
    await waitFor(() => expect(view.getByText('Public Channel')).toBeTruthy())

    const channelSelect = view
      .getAllByRole('combobox')
      .find((el) =>
        Array.from((el as HTMLSelectElement).options).some(
          (o) => o.value === 'government',
        ),
      ) as HTMLSelectElement
    fireEvent.change(channelSelect, { target: { value: 'government' } })

    const submit = view.getByRole('button', { name: /Schedule premiere/i })
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(submit)

    await waitFor(() => expect(createSchedule).toHaveBeenCalledTimes(1))
    expect(vi.mocked(createSchedule).mock.calls[0][0].channel_id).toBe(
      'government',
    )
  })

  it('disables submit and explains when the station has no channels', async () => {
    vi.mocked(listStaffAssets).mockResolvedValue([validatedAsset])
    vi.mocked(listChannelProfiles).mockResolvedValue([])

    const view = renderDrawer()
    await waitFor(() =>
      expect(
        view.getByText('No channels are configured on this station yet.'),
      ).toBeTruthy(),
    )
    const submit = view.getByRole('button', { name: /Schedule premiere/i })
    expect((submit as HTMLButtonElement).disabled).toBe(true)
  })
})

// Beta blocker (LPM native beta, 2026-08-14): clearing the date field made
// the Schedule button do nothing at all. `localIsoToUtcIso` called
// `toISOString()` on an Invalid Date — RangeError — while building the
// payload, which happened OUTSIDE handleSubmit's try/catch. Nothing caught
// it, so no error surfaced and no request was ever sent. The operator saw a
// live button that silently refused to schedule.
describe('ScheduleDrawer unparseable start time', () => {
  function findStartInput(view: ReturnType<typeof renderDrawer>) {
    const input = view.container.querySelector(
      'input[type="datetime-local"]',
    ) as HTMLInputElement
    expect(input).toBeTruthy()
    return input
  }

  async function drawerWithChannels() {
    vi.mocked(listStaffAssets).mockResolvedValue([validatedAsset])
    vi.mocked(listChannelProfiles).mockResolvedValue([
      channelProfile('government', 'Government Channel'),
    ])
    const view = renderDrawer()
    await waitFor(() =>
      expect(view.getByText('Government Channel')).toBeTruthy(),
    )
    return view
  }

  it('does not throw when the date field is cleared', async () => {
    const view = await drawerWithChannels()
    // Pre-fix this render threw RangeError out of the click handler.
    expect(() =>
      fireEvent.change(findStartInput(view), { target: { value: '' } }),
    ).not.toThrow()
  })

  it('disables submit and tells the operator why, instead of failing silently', async () => {
    const view = await drawerWithChannels()
    fireEvent.change(findStartInput(view), { target: { value: '' } })

    const submit = view.getByRole('button', {
      name: /Schedule premiere/i,
    }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(true))
    expect(
      view.getByText('Enter a date and time to schedule this.'),
    ).toBeTruthy()
    expect(findStartInput(view).getAttribute('aria-invalid')).toBe('true')
  })

  it('never sends a request built from an unparseable date', async () => {
    const view = await drawerWithChannels()
    vi.mocked(createSchedule).mockClear()
    fireEvent.change(findStartInput(view), {
      target: { value: 'not-a-date' },
    })

    const submit = view.getByRole('button', { name: /Schedule premiere/i })
    // Click regardless of disabled state — the handler itself must hold.
    expect(() => fireEvent.click(submit)).not.toThrow()
    expect(createSchedule).not.toHaveBeenCalled()
  })

  it('still schedules normally once a valid date is entered again', async () => {
    const view = await drawerWithChannels()
    vi.mocked(createSchedule).mockClear()
    vi.mocked(createSchedule).mockResolvedValue({
      item_id: 'sched-2',
      asset_id: 'asset-1',
      channel_id: 'government',
      mode: 'premiere',
      scheduled_at: '2026-08-20T18:00:00.000Z',
    } as never)

    const input = findStartInput(view)
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.change(input, { target: { value: '2026-08-20T12:00' } })

    const submit = view.getByRole('button', { name: /Schedule premiere/i })
    await waitFor(() =>
      expect((submit as HTMLButtonElement).disabled).toBe(false),
    )
    fireEvent.click(submit)

    await waitFor(() => expect(createSchedule).toHaveBeenCalledTimes(1))
    const sent = vi.mocked(createSchedule).mock.calls[0][0].scheduled_at
    expect(Number.isNaN(new Date(sent as string).getTime())).toBe(false)
  })
})
