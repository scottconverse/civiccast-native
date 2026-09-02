import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  PreflightList,
  PreviewPanel,
  SafeToBroadcastPanel,
  SourceEditForm,
  SourceReadinessDetail,
  SourceSwitcher,
} from './LiveRoomScreen'
import type { LiveSourceResponse } from '../types/live'

/**
 * A source in whatever readiness state the test needs.
 *
 * WP-07: `readiness`, `observation_age_seconds`, `next_action` and the
 * credential-capability fields are all server-derived, because the readiness
 * TTL is a station setting and a client computing staleness from its own clock
 * would disagree with the takeover gate that refuses it.
 */
function source(overrides: Partial<LiveSourceResponse> = {}): LiveSourceResponse {
  return {
    live_source_id: 'sample-source',
    channel_id: 'government',
    name: 'Sample source',
    source_type: 'rtmp',
    endpoint_url: 'rtmp://127.0.0.1/live/sample',
    credentials_handle: null,
    created_at: '2026-07-16T00:00:00Z',
    probe_state: 'never_probed',
    probe_observed_at: null,
    probe_detail: null,
    probe_error_code: null,
    probe_last_success_at: null,
    row_version: 1,
    readiness_ttl_seconds: 30,
    observation_age_seconds: null,
    readiness: 'never_probed',
    credentials_supported: false,
    credentials_unsupported_reason:
      'CivicCast cannot check an RTMP source that needs a username and password.',
    next_action:
      'Sample source has never been checked. Choose Check source to confirm CivicCast can see it before you take air.',
    ...overrides,
  }
}

describe('LiveRoomScreen preview', () => {
  it('does not present simulated video or audio as real source telemetry', () => {
    render(<PreviewPanel source={source()} />)

    expect(screen.getByText('Source preview unavailable')).not.toBeNull()
    expect(screen.getByText(/CivicCast has not verified incoming video or audio/i)).not.toBeNull()
    expect(screen.queryByText('-18 dBFS')).toBeNull()
    expect(screen.queryByLabelText('Source dropped')).toBeNull()
  })
})

describe('LiveRoomScreen pre-flight checklist', () => {
  it('renders the mandated readiness words, never the raw backend enum', () => {
    // UX-REGATE-1/TE-2: this screen was missed by the operator-language sweep and
    // rendered `label={check.status}` -- a raw "pass"/"fail"/"not_configured" enum.
    render(
      <PreflightList
        evaluation={{
          live_session_id: 'sess-1',
          ready: false,
          checks: [
            { name: 'media_probe', status: 'pass', reason_code: null, message: null },
            { name: 'archive_target', status: 'fail', reason_code: 'no_target', message: null },
            { name: 'syndication', status: 'not_configured', reason_code: null, message: null },
          ],
        }}
      />,
    )

    // The guide phrases are on screen...
    expect(screen.getByText('Ready')).not.toBeNull()
    expect(screen.getByText('Do not broadcast yet')).not.toBeNull()
    expect(screen.getByText('Not set up yet')).not.toBeNull()
    // ...and none of the raw enum tokens are.
    expect(screen.queryByText('pass')).toBeNull()
    expect(screen.queryByText('fail')).toBeNull()
    expect(screen.queryByText('not_configured')).toBeNull()
  })

  it('states the do-not-broadcast verdict once, not once per failed check', () => {
    // Banner-wall fix (field survey 2026-08-30): with several failed checks the
    // list used to render an identical "Do not broadcast yet" pill on every
    // row, stacking into a wall of red banners. The verdict now lives in one
    // summary banner; failed rows carry severity via border + next-step copy.
    render(
      <PreflightList
        evaluation={{
          live_session_id: 'sess-2',
          ready: false,
          checks: [
            { name: 'media_probe', status: 'fail', reason_code: 'no_source', message: null },
            { name: 'archive_target', status: 'fail', reason_code: 'no_target', message: null },
            { name: 'syndication', status: 'fail', reason_code: 'no_target', message: null },
          ],
        }}
      />,
    )
    expect(screen.getAllByText('Do not broadcast yet')).toHaveLength(1)
    expect(screen.getByText(/3 pre-flight checks must pass/)).not.toBeNull()
  })
})

describe('LiveRoomScreen broadcast readiness', () => {
  it('shows an explicit fail-closed error and retry action when readiness cannot be checked', () => {
    const onRetry = vi.fn()

    render(
      <SafeToBroadcastPanel
        report={undefined}
        isLoading={false}
        error={new Error('service unavailable')}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByRole('alert').textContent).toMatch(
      /Broadcast readiness could not be checked\. Do not start the stream/i,
    )
    expect(screen.queryByText(/Checking safe-to-broadcast state/i)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Retry check/i }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('uses the checking state only while the readiness request is active', () => {
    render(
      <SafeToBroadcastPanel
        report={undefined}
        isLoading
        error={null}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText(/Checking safe-to-broadcast state/i)).not.toBeNull()
  })
})

describe('LiveRoomScreen source readiness (WP-07 / ENG-003)', () => {
  it('never presents an unchecked source as delivering', () => {
    // The defect this replaces: a configured source was reported ready purely
    // because its row existed, all the way through to the takeover gate.
    render(
      <SourceSwitcher
        sources={[source({ name: 'Council Cam' })]}
        selectedId="sample-source"
        onSelect={vi.fn()}
      />,
    )

    expect(screen.getAllByText('Not checked').length).toBeGreaterThan(0)
    expect(screen.queryByText('Delivering')).toBeNull()
    expect(screen.getAllByText('Never checked').length).toBeGreaterThan(0)
  })

  it('shows the observation age for a source that was checked', () => {
    render(
      <SourceReadinessDetail
        source={source({
          readiness: 'ready',
          probe_state: 'ready',
          observation_age_seconds: 8,
          next_action: 'Sample source is delivering media. You can take air with it.',
        })}
      />,
    )

    expect(screen.getByText('Delivering')).not.toBeNull()
    expect(screen.getByText('Checked 8 seconds ago')).not.toBeNull()
    expect(screen.getByText(/You can take air with it/)).not.toBeNull()
  })

  it('reads a stale observation as needing a re-check, not as ready', () => {
    render(
      <SourceReadinessDetail
        source={source({
          readiness: 'stale',
          probe_state: 'ready',
          observation_age_seconds: 900,
          next_action:
            'The last check of Sample source is older than the readiness window. Choose Check source to confirm it is still delivering before you take air.',
        })}
      />,
    )

    expect(screen.getByText('Needs re-check')).not.toBeNull()
    expect(screen.getByText('Checked 15 minutes ago')).not.toBeNull()
    expect(screen.queryByText('Delivering')).toBeNull()
  })

  it('shows the safe failure reason and the exact next step for a failed source', () => {
    render(
      <SourceReadinessDetail
        source={source({
          readiness: 'failed',
          probe_state: 'failed',
          observation_age_seconds: 12,
          probe_detail: 'Sample source did not respond: Connection refused.',
          probe_error_code: 'probe_refused',
          next_action:
            'Sample source did not answer the last check: Connection refused. Fix the encoder or the address, then choose Check source.',
        })}
      />,
    )

    expect(screen.getByText('Not answering')).not.toBeNull()
    // Twice on purpose: once as the raw reason, once inside the next step.
    expect(screen.getAllByText(/Connection refused/)).toHaveLength(2)
    expect(screen.getByText(/Fix the encoder or the address/)).not.toBeNull()
  })

  it('lets the operator ask for a check and reports that it is running', () => {
    const onCheck = vi.fn()
    const { rerender } = render(
      <SourceReadinessDetail source={source()} onCheck={onCheck} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Check source' }))
    expect(onCheck).toHaveBeenCalledWith('sample-source')

    rerender(<SourceReadinessDetail source={source()} onCheck={onCheck} checking />)
    const busy = screen.getByRole('button', { name: 'Checking source...' })
    expect((busy as HTMLButtonElement).disabled).toBe(true)
  })

  it('explains why editing is unavailable instead of silently hiding it', () => {
    render(
      <SourceReadinessDetail source={source()} onEdit={vi.fn()} canEdit={false} />,
    )

    expect(screen.queryByRole('button', { name: 'Edit source' })).toBeNull()
    expect(screen.getByText(/needs the setup admin role/i)).not.toBeNull()
  })

  it('offers editing to a setup admin', () => {
    const onEdit = vi.fn()
    render(<SourceReadinessDetail source={source()} onEdit={onEdit} canEdit />)

    fireEvent.click(screen.getByRole('button', { name: 'Edit source' }))
    expect(onEdit).toHaveBeenCalled()
  })
})

describe('LiveRoomScreen source edit form', () => {
  it('warns that changing the address clears what CivicCast knows', () => {
    render(
      <SourceEditForm source={source()} onCancel={vi.fn()} onSave={vi.fn()} />,
    )

    // No warning until something readiness-relevant actually changes.
    expect(screen.queryByText(/clears what CivicCast knows/i)).toBeNull()

    fireEvent.change(screen.getByLabelText('Stream address'), {
      target: { value: 'rtmp://127.0.0.1/live/other' },
    })
    expect(screen.getByText(/clears what CivicCast knows/i)).not.toBeNull()
    expect(screen.getByText(/choose Check source again/i)).not.toBeNull()
  })

  it('does not warn for a rename, which does not change what is probed', () => {
    render(
      <SourceEditForm source={source()} onCancel={vi.fn()} onSave={vi.fn()} />,
    )

    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Chamber Cam' },
    })
    expect(screen.queryByText(/clears what CivicCast knows/i)).toBeNull()
  })

  it('sends only the changed fields, plus the row version it loaded', () => {
    const onSave = vi.fn()
    render(<SourceEditForm source={source()} onCancel={vi.fn()} onSave={onSave} />)

    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Chamber Cam' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save source' }))

    expect(onSave).toHaveBeenCalledWith({ name: 'Chamber Cam', expected_row_version: 1 })
  })

  it('disables the credential field for a type that cannot run one, and says why', () => {
    render(<SourceEditForm source={source()} onCancel={vi.fn()} onSave={vi.fn()} />)

    const field = screen.getByLabelText('Stored credential') as HTMLInputElement
    expect(field.disabled).toBe(true)
    expect(
      screen.getByText(/cannot check an RTMP source that needs a username and password/i),
    ).not.toBeNull()
  })

  it('enables the credential field once the type is SRT', () => {
    render(
      <SourceEditForm
        source={source({
          source_type: 'srt',
          endpoint_url: 'srt://0.0.0.0:9000?mode=listener',
          credentials_supported: true,
          credentials_unsupported_reason: null,
        })}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const field = screen.getByLabelText('Stored credential') as HTMLInputElement
    expect(field.disabled).toBe(false)
    expect(screen.getByText(/passphrase itself is never stored here/i)).not.toBeNull()
  })

  it('relabels the address field for NDI, which takes a name not a URL', () => {
    render(
      <SourceEditForm source={source()} onCancel={vi.fn()} onSave={vi.fn()} />,
    )

    fireEvent.change(screen.getByLabelText('Source type'), { target: { value: 'ndi' } })
    expect(screen.getByLabelText('NDI source name')).not.toBeNull()
    expect(screen.getByText(/exactly as the sender advertises it/i)).not.toBeNull()
  })

  it('surfaces a save conflict rather than swallowing it', () => {
    render(
      <SourceEditForm
        source={source()}
        onCancel={vi.fn()}
        onSave={vi.fn()}
        error="sample-source was changed by someone else while you were editing it."
      />,
    )

    expect(screen.getByRole('alert').textContent).toMatch(/changed by someone else/)
  })
})
