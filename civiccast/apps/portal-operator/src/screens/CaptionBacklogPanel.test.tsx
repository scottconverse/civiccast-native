import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as api from '../api/client'
import { CaptionBacklogPanel } from './CaptionBacklogPanel'

vi.mock('../api/client', () => ({ listStaffAssets: vi.fn(), listOfflineCaptionJobs: vi.fn(), queueCaptionBatch: vi.fn(), cancelOfflineCaptionJob: vi.fn(), retryOfflineCaptionJob: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
function mount(canReview = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><CaptionBacklogPanel canReview={canReview} /></QueryClientProvider>)
}
it('queues selected recordings with a ten-recording bound and exposes cancellation/resume/failure', async () => {
  vi.mocked(api.listStaffAssets).mockResolvedValue(Array.from({ length: 11 }, (_, index) => ({ asset_id: `asset-${index}`, title: `Meeting ${index}`, state: 'validated' })) as never)
  vi.mocked(api.listOfflineCaptionJobs).mockResolvedValue([{ job_id: 'cancelled-job', asset_id: 'asset-0', state: 'cancelled', cue_count: 2, published_cue_count: 0, attempts: 1 }, { job_id: 'pending-job', asset_id: 'asset-1', state: 'pending' }, { job_id: 'failed-job', asset_id: 'asset-2', state: 'failed', last_error: 'Repair the caption model' }] as never)
  vi.mocked(api.queueCaptionBatch).mockResolvedValue([{ asset_id: 'asset-0', error: 'Package this recording first' }])
  const view = mount()
  await view.findByLabelText('Select Meeting 0')
  for (let index = 0; index < 10; index++) fireEvent.click(view.getByLabelText(`Select Meeting ${index}`))
  expect((view.getByLabelText('Select Meeting 10') as HTMLInputElement).disabled).toBe(true)
  fireEvent.click(view.getByRole('button', { name: 'Caption selected (10/10)' }))
  await waitFor(() => expect(api.queueCaptionBatch).toHaveBeenCalledWith(Array.from({ length: 10 }, (_, index) => `asset-${index}`), expect.anything()))
  await view.findByText(/Meeting 0: Package this recording first/)
  fireEvent.click(view.getByRole('button', { name: 'Resume' }))
  await waitFor(() => expect(api.retryOfflineCaptionJob).toHaveBeenCalledWith('cancelled-job'))
  fireEvent.click(view.getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(api.cancelOfflineCaptionJob).toHaveBeenCalledWith('pending-job'))
  expect(view.getByText('Repair the caption model')).toBeTruthy()
})
it('keeps backlog visible without write controls for a read-only reviewer', async () => {
  vi.mocked(api.listStaffAssets).mockResolvedValue([{ asset_id: 'one', title: 'Council', state: 'validated' }] as never)
  vi.mocked(api.listOfflineCaptionJobs).mockResolvedValue([])
  const view = mount(false)
  await view.findByLabelText('Select Council')
  expect((view.getByLabelText('Select Council') as HTMLInputElement).disabled).toBe(true)
  expect(view.queryByRole('button', { name: /Caption selected/ })).toBeNull()
  expect(view.getByText('No caption job')).toBeTruthy()
})
