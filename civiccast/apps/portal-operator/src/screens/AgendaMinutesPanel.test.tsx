// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { it, expect, vi } from 'vitest'
import { render, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ApiError, createAgendaMinutes } from '../api/client'
import { AgendaMinutesPanel } from './AgendaMinutesPanel'
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error { detail: string; constructor(message: string, _status: number, detail: string) { super(message); this.detail = detail } },
  getStaffIdentity: vi.fn().mockResolvedValue({ roles: ['records_clerk'] }),
  listSummaryReviewItems: vi.fn().mockResolvedValue({ items: [] }),
  createAgendaMinutes: vi.fn(),
}))
it('explains the caption-review refusal and links to review', async () => {
  vi.mocked(createAgendaMinutes).mockRejectedValue(new ApiError('Conflict', 409, 'Finish English caption review before drafting minutes.'))
  const view = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><AgendaMinutesPanel agendaId="agenda" assetId="asset" /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(view.getByRole('button', { name: 'Draft meeting minutes' }))
  const button = await view.findByRole('button', { name: 'Create draft minutes' })
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(button)
  expect((await view.findByRole('alert')).textContent).toContain('Finish English caption review')
  expect(view.getByRole('link', { name: 'Open caption review' }).getAttribute('href')).toBe('/review')
  cleanup()
})
