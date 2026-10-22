// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'

afterEach(() => vi.unstubAllGlobals())

it.each([true, false])('submits a schedulable requested date (present: %s)', async (withDate) => {
  let submitted: { requested_air_date: string | null } | undefined
  const json = (body: unknown) => new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/contribute/uploads')) {
      return json({ upload_ref: 'owned-upload', filename: 'fixture.mp4', content_type: 'video/mp4', size_bytes: 1 })
    }
    if (url.endsWith('/contribute/submissions')) {
      submitted = JSON.parse(init?.body as string)
      return json({ submission_id: 'owned-submission', receipt_token: 'private-test-receipt', state: 'submitted' })
    }
    if (url.includes('/contribute/agreements/current')) return json({ agreement_id: 'test', version: '1' })
    if (url.includes('/schedule/coming-up') || url.includes('/assets')) return json([])
    if (url.includes('/live/current')) return json({ state: 'offline', channel_id: 'public' })
    return json(null)
  }))
  render(<HomeScreen />)
  const title = await screen.findByLabelText('Program title')
  fireEvent.change(screen.getByLabelText('Producer name'), { target: { value: 'Test producer' } })
  fireEvent.change(screen.getByLabelText('Email', { exact: true }), { target: { value: 'test@example.invalid' } })
  fireEvent.change(title, { target: { value: 'Owned fixture' } })
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Owned acceptance fixture' } })
  fireEvent.change(screen.getByLabelText('Video file'), {
    target: { files: [new File(['x'], 'fixture.mp4', { type: 'video/mp4' })] },
  })
  if (withDate) fireEvent.change(screen.getByLabelText('Requested air date'), { target: { value: '2026-10-22T01:07' } })
  fireEvent.submit(title.closest('form')!)
  await waitFor(() => expect(submitted).toBeDefined())
  if (withDate) {
    // The scheduler rejects naive dates. Preserve the resident's local instant
    // while including an explicit timezone, including on non-UTC machines.
    expect(submitted!.requested_air_date).toMatch(/T\d{2}:\d{2}:\d{2}\.\d{3}Z$/)
    expect(Date.parse(submitted!.requested_air_date!)).toBe(new Date(2026, 9, 22, 1, 7).getTime())
  } else {
    expect(submitted!.requested_air_date).toBeNull()
  }
})
