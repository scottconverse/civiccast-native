import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PreflightList, PreviewPanel, SafeToBroadcastPanel } from './LiveRoomScreen'

describe('LiveRoomScreen preview', () => {
  it('does not present simulated video or audio as real source telemetry', () => {
    render(
      <PreviewPanel
        source={{
          live_source_id: 'sample-source',
          channel_id: 'government',
          name: 'Sample source',
          source_type: 'rtmp',
          endpoint_url: 'rtmp://127.0.0.1/live/sample',
          credentials_handle: null,
          created_at: '2026-07-16T00:00:00Z',
        }}
      />,
    )

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
