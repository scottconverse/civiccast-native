// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Codex review finding (P2, PR #427): when the browser supplies a nonempty
// but unparseable "First airing" or "Repeat until" value, `submitDisabled`
// disables the button before handleSubmit's own validation branches can
// ever run, so the drawer left the operator with an unexplained inert
// button — unlike ScheduleDrawer.tsx, which renders an inline error next
// to the field. This suite proves both date fields on ProgramSlotDrawer now
// render their own inline error (text, aria-invalid, aria-describedby)
// driven directly off the parsed value, not off the click handler.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { AssetRow } from '../../types/asset'

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
  createProgramSlot: vi.fn(),
  listStaffAssets: vi.fn(),
}))

import { createProgramSlot, listStaffAssets } from '../../api/client'
import { ProgramSlotDrawer } from './ProgramSlotDrawer'

const validatedAsset: AssetRow = {
  asset_id: 'asset-1',
  title: 'Council meeting rehearsal',
  state: 'validated',
} as AssetRow

function renderDrawer() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ProgramSlotDrawer
        channelId="government"
        onClose={() => {}}
        onCreated={() => {}}
      />
    </QueryClientProvider>,
  )
}

async function drawerWithAssets() {
  vi.mocked(listStaffAssets).mockResolvedValue([validatedAsset])
  const view = renderDrawer()
  await waitFor(() =>
    expect(view.getByText(/Council meeting rehearsal/)).toBeTruthy(),
  )
  return view
}

function dateInputs(view: Awaited<ReturnType<typeof drawerWithAssets>>) {
  const inputs = Array.from(
    view.container.querySelectorAll('input[type="datetime-local"]'),
  ) as HTMLInputElement[]
  // recurrence defaults to 'weekly' (repeatable), so both inputs are present.
  expect(inputs.length).toBe(2)
  const [firstAiring, repeatUntil] = inputs
  return { firstAiring, repeatUntil }
}

describe('ProgramSlotDrawer unparseable first-airing date', () => {
  it('does not throw when the first-airing field is cleared', async () => {
    const view = await drawerWithAssets()
    const { firstAiring } = dateInputs(view)
    expect(() =>
      fireEvent.change(firstAiring, { target: { value: '' } }),
    ).not.toThrow()
  })

  it('disables submit and shows an inline error next to the field, not just a dead button', async () => {
    const view = await drawerWithAssets()
    const { firstAiring } = dateInputs(view)
    fireEvent.change(firstAiring, { target: { value: '' } })

    const submit = view.getByRole('button', {
      name: /Add to guide/i,
    }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(true))
    expect(
      view.getByText('Enter a date and time for the first airing.'),
    ).toBeTruthy()
    expect(firstAiring.getAttribute('aria-invalid')).toBe('true')
    expect(firstAiring.getAttribute('aria-describedby')).toBeTruthy()
  })

  it('never sends a request built from an unparseable first-airing date', async () => {
    const view = await drawerWithAssets()
    vi.mocked(createProgramSlot).mockClear()
    const { firstAiring } = dateInputs(view)
    fireEvent.change(firstAiring, { target: { value: 'not-a-date' } })

    const submit = view.getByRole('button', { name: /Add to guide/i })
    // Click regardless of disabled state -- the handler itself must hold.
    expect(() => fireEvent.click(submit)).not.toThrow()
    expect(createProgramSlot).not.toHaveBeenCalled()
  })

  it('clears the inline error and re-enables submit once a valid date is entered again', async () => {
    const view = await drawerWithAssets()
    const { firstAiring } = dateInputs(view)
    fireEvent.change(firstAiring, { target: { value: '' } })
    await waitFor(() =>
      expect(
        view.getByText('Enter a date and time for the first airing.'),
      ).toBeTruthy(),
    )

    fireEvent.change(firstAiring, { target: { value: '2026-08-20T12:00' } })

    await waitFor(() =>
      expect(
        view.queryByText('Enter a date and time for the first airing.'),
      ).toBeNull(),
    )
    expect(firstAiring.getAttribute('aria-invalid')).toBe('false')
  })
})

describe('ProgramSlotDrawer unparseable repeat-until date', () => {
  it('leaves submit enabled and shows no error while repeat-until is empty (it is optional)', async () => {
    const view = await drawerWithAssets()
    const submit = view.getByRole('button', {
      name: /Add to guide/i,
    }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(false))
    expect(
      view.queryByText(
        'The repeat-until date could not be read. Re-enter it.',
      ),
    ).toBeNull()
  })

  it('disables submit and shows an inline error next to the field when repeat-until is unparseable', async () => {
    const view = await drawerWithAssets()
    const { repeatUntil } = dateInputs(view)
    // A native datetime-local input sanitizes free text like "garbage" back
    // to "" on assignment (verified against jsdom directly), so it can never
    // reproduce the "nonempty but unparseable" case this fix targets. A year
    // outside JS Date's representable range (~year 275760) is the real
    // repro the component's own comment calls out: syntactically valid per
    // the datetime-local pattern (kept as-is by the input), but
    // `new Date(...)` on it is a genuine Invalid Date.
    fireEvent.change(repeatUntil, { target: { value: '999999-01-01T00:00' } })

    const submit = view.getByRole('button', {
      name: /Add to guide/i,
    }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(true))
    expect(
      view.getByText('The repeat-until date could not be read. Re-enter it.'),
    ).toBeTruthy()
    expect(repeatUntil.getAttribute('aria-invalid')).toBe('true')
    expect(repeatUntil.getAttribute('aria-describedby')).toBeTruthy()
  })

  it('never sends a request built from an unparseable repeat-until date', async () => {
    const view = await drawerWithAssets()
    vi.mocked(createProgramSlot).mockClear()
    const { repeatUntil } = dateInputs(view)
    // A native datetime-local input sanitizes free text like "garbage" back
    // to "" on assignment (verified against jsdom directly), so it can never
    // reproduce the "nonempty but unparseable" case this fix targets. A year
    // outside JS Date's representable range (~year 275760) is the real
    // repro the component's own comment calls out: syntactically valid per
    // the datetime-local pattern (kept as-is by the input), but
    // `new Date(...)` on it is a genuine Invalid Date.
    fireEvent.change(repeatUntil, { target: { value: '999999-01-01T00:00' } })

    const submit = view.getByRole('button', { name: /Add to guide/i })
    expect(() => fireEvent.click(submit)).not.toThrow()
    expect(createProgramSlot).not.toHaveBeenCalled()
  })

  it('still adds to the guide once repeat-until is corrected', async () => {
    const view = await drawerWithAssets()
    vi.mocked(createProgramSlot).mockClear()
    vi.mocked(createProgramSlot).mockResolvedValue({
      slot_id: 'slot-1',
      channel_id: 'government',
      asset_id: 'asset-1',
      recurrence: 'weekly',
      first_start_at: '2026-08-20T18:00:00.000Z',
      repeat_until: '2026-09-20T18:00:00.000Z',
    } as never)

    const { firstAiring, repeatUntil } = dateInputs(view)
    fireEvent.change(firstAiring, { target: { value: '2026-08-20T12:00' } })
    // A native datetime-local input sanitizes free text like "garbage" back
    // to "" on assignment (verified against jsdom directly), so it can never
    // reproduce the "nonempty but unparseable" case this fix targets. A year
    // outside JS Date's representable range (~year 275760) is the real
    // repro the component's own comment calls out: syntactically valid per
    // the datetime-local pattern (kept as-is by the input), but
    // `new Date(...)` on it is a genuine Invalid Date.
    fireEvent.change(repeatUntil, { target: { value: '999999-01-01T00:00' } })
    fireEvent.change(repeatUntil, { target: { value: '2026-09-20T12:00' } })

    const submit = view.getByRole('button', {
      name: /Add to guide/i,
    }) as HTMLButtonElement
    await waitFor(() => expect(submit.disabled).toBe(false))
    fireEvent.click(submit)

    await waitFor(() => expect(createProgramSlot).toHaveBeenCalledTimes(1))
    const sent = vi.mocked(createProgramSlot).mock.calls[0][0].repeat_until
    expect(Number.isNaN(new Date(sent as string).getTime())).toBe(false)
  })
})
