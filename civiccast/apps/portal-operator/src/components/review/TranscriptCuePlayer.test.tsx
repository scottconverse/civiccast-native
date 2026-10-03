import { afterEach, expect, it, vi } from 'vitest'
import { act, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SummarySourceEvidence } from './TranscriptCuePlayer'
import type { SummaryGenerationJobRecord } from '../../types/api.generated'

const range = { cue_id: 'shared', start_seconds: 1, end_seconds: 2 }
const cue = { ...range, text: 'Original source words.', confidence: 1 }
const job = { job_id: 'job', meeting_id: 'meeting', summary_id: 'summary', state: 'complete', cues: [cue], created_at: '', updated_at: '' } satisfies SummaryGenerationJobRecord
const clients: QueryClient[] = []
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; vi.unstubAllGlobals() })
function show(summaryId = 'summary') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  const element = (id: string) => <QueryClientProvider client={client}><SummarySourceEvidence meetingId="meeting" summaryId={id} selectedRange={range} /></QueryClientProvider>
  const view = render(element(summaryId))
  return { ...view, changeSummary: (id: string) => view.rerender(element(id)) }
}
function respond(rows: unknown) { return new Response(JSON.stringify(rows), { headers: { 'Content-Type': 'application/json' } }) }

it.each([
  [[], /no matching completed job/],
  [[{ ...job, summary_id: 'different-summary' }], /no matching completed job/],
  [[{ ...job, meeting_id: 'different-meeting' }], /no matching completed job/],
  [[{ ...job, state: 'running' }], /no matching completed job/],
  [[job, { ...job, job_id: 'duplicate' }], /multiple completed jobs/],
  [[{ ...job, cues: [] }], /exact cue range is missing/],
  [[{ ...job, cues: [{ ...cue, cue_id: 'different-cue' }] }], /exact cue range is missing/],
  [[{ ...job, cues: [cue, cue] }], /duplicate cue ranges/],
  [[{ ...job, cues: [{ ...cue, start_seconds: 1.5 }] }], /exact cue range is missing/],
  [[{ ...job, cues: [{ ...cue, text: ' ' }] }], /source caption is empty/],
])('does not invent source words for unavailable/ambiguous inputs (%j)', async (rows, message) => {
  vi.stubGlobal('fetch', vi.fn(async () => respond(rows)))
  const view = show()
  await view.findByText(message as RegExp)
  expect(view.queryByText(cue.text)).toBeNull()
})

it('supports a cited subrange and identifies the full source cue rather than claiming word alignment', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => respond([{ ...job, cues: [{ ...cue, start_seconds: 0, end_seconds: 3 }] }])))
  const view = show()
  await view.findByText(cue.text)
  expect(view.getByText(/Full source cue: 0:00-0:03/)).toBeTruthy()
})

it('leaves an unselected second summary untouched even when it shares the same cue ID', async () => {
  const fetcher = vi.fn(async () => respond([job]))
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  const view = render(<QueryClientProvider client={client}>
    <SummarySourceEvidence meetingId="meeting" summaryId="summary" selectedRange={range} />
    <SummarySourceEvidence meetingId="other-meeting" summaryId="other-summary" selectedRange={null} />
  </QueryClientProvider>)
  await view.findByText(cue.text)
  expect(view.getByText('Select a source range to read the caption words used for generation.')).toBeTruthy()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('shows loading, reports a request failure and retries the exact meeting query', async () => {
  let finish: ((response: Response) => void) | undefined
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve })).mockResolvedValue(respond([job]))
  vi.stubGlobal('fetch', fetcher)
  const view = show()
  await view.findByText('Loading generation source captions.')
  await act(async () => { finish?.(new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 503 })) })
  fireEvent.click(await view.findByRole('button', { name: 'Retry source captions' }))
  await view.findByText(cue.text)
  expect(String(fetcher.mock.calls[1][0])).toContain('meeting_id=meeting&state=complete')
})

it('does not show a late previous-summary response in the new summary', async () => {
  let finishOld: ((response: Response) => void) | undefined
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve })).mockResolvedValue(respond([{ ...job, summary_id: 'new-summary', cues: [{ ...cue, text: 'New source words.' }] }]))
  vi.stubGlobal('fetch', fetcher)
  const view = show()
  await view.findByText('Loading generation source captions.')
  view.changeSummary('new-summary')
  await view.findByText('New source words.')
  await act(async () => { finishOld?.(respond([job])) })
  expect(view.queryByText(cue.text)).toBeNull()
  expect(view.getByText('New source words.')).toBeTruthy()
})
