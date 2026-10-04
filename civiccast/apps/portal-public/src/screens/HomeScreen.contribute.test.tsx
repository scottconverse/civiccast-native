// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HomeScreen } from './HomeScreen'

vi.mock('../HlsPlayer', () => ({ HlsPlayer: () => null }))

let submitted: Record<string, unknown> | undefined

beforeEach(() => {
  submitted = undefined
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    let body: unknown = null
    if (url.includes('/schedule/coming-up') || url.endsWith('/assets')) body = []
    if (url.endsWith('/agreements/current')) {
      body = { agreement_id: 'community', version: '1', title: 'Agreement', summary: 'Review required' }
    }
    if (url.endsWith('/contribute/uploads')) body = { asset_id: 'uploaded-video' }
    if (url.endsWith('/contribute/submissions')) {
      submitted = JSON.parse(String(init?.body)) as Record<string, unknown>
      body = { submission_id: 'submission-1', receipt_token: 'test-receipt' }
    }
    return new Response(JSON.stringify(body), { status: 200 })
  }))
})

afterEach(() => vi.unstubAllGlobals())

describe('contributor requested air time', () => {
  it.each(['2026-10-05T18:30', ''])('submits a schedulable instant or no preference (%s)', async (value) => {
    render(<HomeScreen />)
    await screen.findByRole('button', { name: 'Send to review' })
    for (const [label, text] of Object.entries({
      'Producer name': 'Community Producer', Email: 'producer@example.org',
      'Program title': 'Local program', Description: 'Community video',
    })) fireEvent.change(screen.getByLabelText(label), { target: { value: text } })
    fireEvent.change(screen.getByLabelText(/Requested air date/), { target: { value } })
    fireEvent.change(screen.getByLabelText('Video file'), {
      target: { files: [new File(['video'], 'program.mp4', { type: 'video/mp4' })] },
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Send to review' }).closest('form')!)
    await waitFor(() => expect(submitted).toBeDefined())
    expect(submitted?.requested_air_date).toBe(value ? new Date(2026, 9, 5, 18, 30).toISOString() : null)
    expect(submitted?.channel_id).toBe('public')
    expect(await screen.findByText('Your program was sent to the station review queue.')).toBeTruthy()
  })
})
