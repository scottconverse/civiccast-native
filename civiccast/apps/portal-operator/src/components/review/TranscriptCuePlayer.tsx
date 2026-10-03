import { useQuery } from '@tanstack/react-query'
import { listSummaryJobs } from '../../api/client'
import type { TranscriptRange } from '../../types/api.generated'

function fmtTime(value: number): string {
  const whole = Math.floor(value)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** Read retained generation input, never today's edited captions or claim text. */
export function SummarySourceEvidence({ meetingId, summaryId, selectedRange }: {
  meetingId: string
  summaryId: string
  selectedRange: TranscriptRange | null
}) {
  const query = useQuery({
    queryKey: ['summary-source-jobs', meetingId, summaryId],
    queryFn: () => listSummaryJobs({ meetingId, state: 'complete' }),
    enabled: selectedRange !== null,
    retry: false,
  })
  const jobs = (query.data ?? []).filter((job) => job.meeting_id === meetingId && job.summary_id === summaryId && job.state === 'complete')
  const cues = jobs.length === 1 && selectedRange
    ? (jobs[0].cues ?? []).filter((cue) => cue.cue_id === selectedRange.cue_id && cue.start_seconds <= selectedRange.start_seconds && cue.end_seconds >= selectedRange.end_seconds)
    : []
  let message = 'Select a source range to read the caption words used for generation.'
  if (selectedRange) {
    if (query.isPending || query.isFetching) message = 'Loading generation source captions.'
    else if (query.isError) message = 'Could not load generation source captions. Retry this request.'
    else if (jobs.length === 0) message = 'Original generation source unavailable: no matching completed job was retained. Current captions and claim text are not substituted.'
    else if (jobs.length > 1) message = 'Original generation source is ambiguous: multiple completed jobs match this summary.'
    else if (cues.length === 0) message = 'Original generation source unavailable: this exact cue range is missing from the retained job.'
    else if (cues.length > 1) message = 'Original generation source is ambiguous: duplicate cue ranges in the retained job.'
    else if (!cues[0].text.trim()) message = 'The retained source caption is empty.'
    else message = ''
  }
  return (
    <section aria-label="Source captions" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)', overflowWrap: 'anywhere' }}>
      <div className="font-semibold">Source captions (not audio playback)</div>
      {selectedRange && <div>{selectedRange.cue_id} {fmtTime(selectedRange.start_seconds)}-{fmtTime(selectedRange.end_seconds)}</div>}
      {message && <div role={query.isError && selectedRange ? 'alert' : 'status'}>{message}</div>}
      {selectedRange && !query.isPending && !query.isFetching && message && !query.isError && <div>Next step: check the recording and approved captions through your station's review workflow before approving an uncertain claim.</div>}
      {selectedRange && query.isError && <button type="button" disabled={query.isFetching} onClick={() => query.refetch()}>Retry source captions</button>}
      {selectedRange && !message && <>
        <div>Retained generation input / job {jobs[0].job_id}</div>
        <div>Full source cue: {fmtTime(cues[0].start_seconds)}-{fmtTime(cues[0].end_seconds)}. Words below cover the full cue, not an audio-aligned excerpt.</div>
        <p className="whitespace-pre-wrap">{cues[0].text}</p>
      </>}
    </section>
  )
}
