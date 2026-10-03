// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { SummaryDraft } from '../types/api.generated'
import { SummaryReviewScreen } from './SummaryReviewScreen'

const draft: SummaryDraft = {
  summary_id: 'workflow-summary', meeting_id: 'workflow-meeting', status: 'pending_review',
  narrative: 'The motion passed.',
  sourced_claims: [{ claim_id: 'claim', claim_type: 'narrative', text: 'The motion passed.',
    transcript_ranges: [{ cue_id: 'cue', start_seconds: 1, end_seconds: 2 }] }],
  provenance: { model_tag: 'deterministic-test', prompt_version: 'test', extraction_version: 'test',
    generated_at: '2026-10-03T00:00:00Z', runtime_parameters: {} },
  audit_fingerprint: `sha256:${'b'.repeat(64)}`,
}
const clients: QueryClient[] = []
afterEach(() => {
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.localStorage.clear()
})

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function backend(options: { approved?: boolean; approvalRequired?: boolean; identity?: 'pending' | 'failed' | 'nonclerk'; failOnce?: 'approve' | 'export' | 'download' | 'verify'; verificationFailed?: boolean; verificationPending?: boolean; missingArtifactDigest?: boolean } = {}) {
  let summary = { ...draft, status: options.approved ? 'approved' : 'pending_review' } as SummaryDraft
  let failed = false
  let finishVerification: ((result: Response) => void) | undefined
  const requests: { url: string; body: Record<string, unknown> }[] = []
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input)
    const operation = url.endsWith('/approve') ? 'approve' : url.endsWith('/download') ? 'download' : url.endsWith('/verify') ? 'verify' : url.endsWith('/api/staff/records') ? 'export' : null
    if (operation === options.failOnce && !failed) { failed = true; return response({ detail: `${operation} service unavailable.` }, 503) }
    if (url.endsWith('/api/staff/auth/me')) {
      if (options.identity === 'pending') return new Promise<Response>(() => {})
      if (options.identity === 'failed') return response({ detail: 'Identity unavailable.' }, 503)
      return response({ operator_id: 'clerk', operator_display_name: 'Test Clerk', roles: options.identity === 'nonclerk' ? ['meeting_operator'] : ['records_clerk'] })
    }
    if (url.includes('/summaries/review-items')) {
      const includeApproved = url.includes('include_approved=true')
      return response({ items: summary.status !== 'approved' || includeApproved ? [summary] : [], next_cursor: null, approval_required_summary_ids: options.approvalRequired ? [summary.summary_id] : [] })
    }
    if (url.includes('/summaries/jobs?')) return response([
      { job_id: 'wrong-meeting', meeting_id: 'another-meeting', summary_id: draft.summary_id, state: 'complete', cues: [{ cue_id: 'cue', start_seconds: 1, end_seconds: 2, text: 'Wrong meeting words.', confidence: 1 }] },
      { job_id: 'original-job', meeting_id: draft.meeting_id, summary_id: draft.summary_id, state: 'complete', cues: [{ cue_id: 'cue', start_seconds: 1, end_seconds: 2, text: 'Original caption words used for generation.', confidence: 1 }] },
    ])
    if (url.endsWith('/approve')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      requests.push({ url, body })
      if (Object.keys(body).some((key) => key !== 'approval_note')) return response({ detail: 'Extra approval fields are forbidden.' }, 422)
      summary = { ...summary, status: 'approved' }
      options.approvalRequired = false
      return response(summary)
    }
    if (url.endsWith('/api/staff/records')) return response({ record_id: 'record', summary_id: draft.summary_id,
      pdfa: { file_name: 'workflow-record.pdf' }, artifact_digest: options.missingArtifactDigest ? undefined : 'final-pdf-digest', timestamp_proof: { artifact_digest: 'timestamp-input-digest' } }, 201)
    if (url.endsWith('/download')) {
      expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer workflow-test-token')
      return new Response('%PDF-test', { headers: { 'Content-Type': 'application/pdf' } })
    }
    if (url.endsWith('/verify')) {
      expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer workflow-test-token')
      if (options.verificationPending) return new Promise<Response>((resolve) => { finishVerification = resolve })
      return response({ record_id: 'record', status: options.verificationFailed ? 'failed' : 'verified', timestamp_proof: { tsa_url: null } })
    }
    throw new Error(`Unexpected test request: ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  return { requests, fetcher, completeVerification: () => finishVerification?.(response({ record_id: 'record', status: 'verified', timestamp_proof: { tsa_url: null } })) }
}

function screen(cachedIdentity = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (cachedIdentity) client.setQueryData(['staff-identity'], { operator_id: 'prior-clerk', roles: ['records_clerk'] })
  clients.push(client)
  return render(<QueryClientProvider client={client}><SummaryReviewScreen /></QueryClientProvider>)
}

describe('summary approval real serialized client contract', () => {
  it('shows original generation caption words, not claim text or another meeting with the same cue ID', async () => {
    backend()
    const view = screen()
    fireEvent.click(await view.findByRole('button', { name: /cue 0:01-0:02/ }))
    await view.findByText('Original caption words used for generation.')
    expect(view.queryByText('Wrong meeting words.')).toBeNull()
  })
  it('requires explicit authenticated reapproval for an orphan approved summary before export', async () => {
    const api = backend({ approved: true, approvalRequired: true })
    const view = screen()
    const reapprove = await view.findByRole('button', { name: 'Reapprove summary' })
    await waitFor(() => expect((reapprove as HTMLButtonElement).disabled).toBe(false))
    expect((view.getByRole('button', { name: 'Export signed record' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(reapprove)
    await waitFor(() => expect(api.requests).toHaveLength(1))
    expect(api.requests[0].body).toEqual({ approval_note: 'Approved after checking sourced-claim transcript links.' })
    await waitFor(() => expect((view.getByRole('button', { name: 'Export signed record' }) as HTMLButtonElement).disabled).toBe(false))
    expect(view.queryByRole('button', { name: 'Reapprove summary' })).toBeNull()
    expect((view.getByRole('button', { name: 'Approve summary' }) as HTMLButtonElement).disabled).toBe(true)
  })
  it.each([false, true])('labels the final PDF checksum honestly (missing field: %s)', async (missingArtifactDigest) => {
    backend({ approved: true, missingArtifactDigest })
    const view = screen()
    const exportButton = await view.findByRole('button', { name: 'Export signed record' })
    await waitFor(() => expect((exportButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(exportButton)
    await view.findByText(missingArtifactDigest ? 'PDF SHA-256: unavailable in this response.' : 'PDF SHA-256: final-pdf-digest')
    expect(view.queryByText(/timestamp-input-digest/)).toBeNull()
  })
  it('disables an old download Retry while verification is pending, then restores it', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'workflow-test-token')
    const api = backend({ approved: true, failOnce: 'download', verificationPending: true })
    const view = screen()
    const exportButton = await view.findByRole('button', { name: 'Export signed record' })
    await waitFor(() => expect((exportButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(exportButton)
    fireEvent.click(await view.findByRole('button', { name: 'Download PDF' }))
    await view.findByText('Signed record was exported, but the PDF download failed.')
    fireEvent.click(view.getByRole('button', { name: 'Verify record' }))
    await view.findByText('Checking signed-record integrity and timestamp proof structure.')
    const retry = view.getByRole('button', { name: 'Retry' }) as HTMLButtonElement
    expect(retry.disabled).toBe(true)
    const calls = api.fetcher.mock.calls.length
    fireEvent.click(retry)
    expect(api.fetcher.mock.calls).toHaveLength(calls)
    api.completeVerification()
    await waitFor(() => expect(retry.disabled).toBe(false))
  })
  it('shows verification checking state and prevents concurrent record actions', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'workflow-test-token')
    backend({ approved: true, verificationPending: true })
    const view = screen()
    const exportButton = await view.findByRole('button', { name: 'Export signed record' })
    await waitFor(() => expect((exportButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(exportButton)
    fireEvent.click(await view.findByRole('button', { name: 'Verify record' }))
    await view.findByText('Checking signed-record integrity and timestamp proof structure.')
    expect((view.getByRole('button', { name: 'Verify record' }) as HTMLButtonElement).disabled).toBe(true)
    expect((view.getByRole('button', { name: 'Download PDF' }) as HTMLButtonElement).disabled).toBe(true)
  })
  it.each(['verify', 'failed'] as const)('shows and retries %s verification without claiming an external timestamp authority', async (mode) => {
    window.localStorage.setItem('civiccast.staffToken', 'workflow-test-token')
    const options: NonNullable<Parameters<typeof backend>[0]> = { approved: true, failOnce: mode === 'verify' ? 'verify' : undefined, verificationFailed: mode === 'failed' }
    backend(options)
    const view = screen()
    const exportButton = await view.findByRole('button', { name: 'Export signed record' })
    await waitFor(() => expect((exportButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(exportButton)
    fireEvent.click(await view.findByRole('button', { name: 'Verify record' }))
    await view.findByText('Could not verify signed record.')
    options.verificationFailed = false
    fireEvent.click(view.getByRole('button', { name: 'Retry' }))
    await view.findByText('Record verification passed. Deterministic test timestamp; no external timestamp authority was verified.')
    expect(view.queryByText('Could not verify signed record.')).toBeNull()
  })
  it('sends only the supported note and keeps export available after refetch', async () => {
    const api = backend()
    const view = screen()
    const approve = await view.findByRole('button', { name: 'Approve summary' })
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(approve)
    await waitFor(() => expect(api.requests).toHaveLength(1))
    expect(api.requests[0].body).toEqual({ approval_note: 'Approved after checking sourced-claim transcript links.' })
    await waitFor(() => expect((view.getByRole('button', { name: 'Export signed record' }) as HTMLButtonElement).disabled).toBe(false))
  })

  it('finds an already approved summary on a fresh page load', async () => {
    backend({ approved: true })
    const view = screen()
    const button = await view.findByRole('button', { name: 'Export signed record' })
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  })

  it.each(['pending', 'failed', 'nonclerk'] as const)('keeps actions disabled for %s identity', async (identity) => {
    backend({ identity })
    const view = screen()
    const approve = await view.findByRole('button', { name: 'Approve summary' })
    if (identity !== 'pending') await waitFor(() => expect(view.getByRole('alert')).toBeTruthy())
    expect((approve as HTMLButtonElement).disabled).toBe(true)
    expect((view.getByRole('button', { name: 'Export signed record' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not trust a cached clerk role while identity is being refreshed', async () => {
    backend({ identity: 'pending' })
    const view = screen(true)
    const approve = await view.findByRole('button', { name: 'Approve summary' })
    expect((approve as HTMLButtonElement).disabled).toBe(true)
  })

  it('disables approval retry while the cached identity is being refreshed', async () => {
    const options: NonNullable<Parameters<typeof backend>[0]> = { failOnce: 'approve' }
    backend(options)
    const view = screen()
    const approve = await view.findByRole('button', { name: 'Approve summary' })
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(approve)
    await view.findByText('Could not approve summary.')
    options.identity = 'pending'
    void clients.at(-1)!.invalidateQueries({ queryKey: ['staff-identity'] })
    await view.findByRole('status')
    expect((view.getByRole('button', { name: 'Retry' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it.each(['approve', 'export', 'download'] as const)('distinguishes and actually retries %s failure', async (operation) => {
    window.localStorage.setItem('civiccast.staffToken', 'workflow-test-token')
    backend({ approved: operation !== 'approve', failOnce: operation })
    const create = vi.fn(() => 'blob:test-record')
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = create
      static revokeObjectURL = revoke
    })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const view = screen()
    const action = await view.findByRole('button', { name: operation === 'approve' ? 'Approve summary' : 'Export signed record' })
    await waitFor(() => expect((action as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(action)
    if (operation === 'download') fireEvent.click(await view.findByRole('button', { name: 'Download PDF' }))
    const heading = operation === 'approve' ? 'Could not approve summary.' : operation === 'export' ? 'Could not export signed record.' : 'Signed record was exported, but the PDF download failed.'
    await view.findByText(heading)
    fireEvent.click(view.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(view.queryByText(heading)).toBeNull())
    if (operation === 'download') {
      expect(create).toHaveBeenCalledOnce()
      expect(revoke).toHaveBeenCalledWith('blob:test-record')
      expect(click).toHaveBeenCalledOnce()
    }
    click.mockRestore()
  })
})
