import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Full-screen tests (role gating, the readiness poll, and the 409-conflict
// reload) need the real API surface mocked -- LiveRoomScreen itself imports
// every one of these. The component-level tests below (SourceSwitcher,
// SourceReadinessDetail, SourceEditForm rendered directly) never call any of
// these, so the mock is a safe no-op for them.
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  createLiveSession: vi.fn(),
  endLiveBroadcast: vi.fn(),
  evaluateLivePreflight: vi.fn(),
  getLiveFinalizationStatus: vi.fn(),
  getLiveIngestPlan: vi.fn(),
  getLiveSession: vi.fn(),
  getLiveSourceById: vi.fn(),
  getSafeToBroadcast: vi.fn(),
  getSourceSetup: vi.fn(),
  getStaffIdentity: vi.fn(),
  goLiveOnAir: vi.fn(),
  listChannelProfiles: vi.fn(),
  listLiveSources: vi.fn(),
  listRecordingTargets: vi.fn(),
  probeLiveSource: vi.fn(),
  retryLiveFinalization: vi.fn(),
  startLivePreflight: vi.fn(),
  updateLiveSource: vi.fn(),
}))

import {
  ApiError,
  getLiveIngestPlan,
  getLiveSourceById,
  getSafeToBroadcast,
  getSourceSetup,
  getStaffIdentity,
  listChannelProfiles,
  listLiveSources,
  listRecordingTargets,
  updateLiveSource,
} from '../api/client'
import {
  LiveRoomScreen,
  PreflightList,
  PreviewPanel,
  SafeToBroadcastPanel,
  SourceEditForm,
  SourceReadinessDetail,
  SourceSwitcher,
} from './LiveRoomScreen'
import type { LiveSourceResponse } from '../types/live'
import type {
  ChannelProfile,
  LiveIngestPlan,
  SourceSetupReport,
  StaffIdentityResponse,
  SystemHealthReport,
} from '../types/api.generated'

afterEach(cleanup)

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
      <SourceReadinessDetail source={source()} onCheck={onCheck} canCheck />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Check source' }))
    expect(onCheck).toHaveBeenCalledWith('sample-source')

    rerender(
      <SourceReadinessDetail source={source()} onCheck={onCheck} canCheck checking />,
    )
    const busy = screen.getByRole('button', { name: 'Checking source...' })
    expect((busy as HTMLButtonElement).disabled).toBe(true)
  })

  it('hides Check source and explains why when the identity lacks the role, matching the backend gate', () => {
    render(<SourceReadinessDetail source={source()} onCheck={vi.fn()} canCheck={false} />)

    expect(screen.queryByRole('button', { name: 'Check source' })).toBeNull()
    expect(
      screen.getByText(/needs the meeting operator or setup admin role/i),
    ).not.toBeNull()
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

  it('clears the stored credential when the type is switched away from SRT, so it cannot be resubmitted after switching back', () => {
    // Before this fix, switching the type away from SRT only blanked the
    // credential field VISUALLY (the input is disabled-and-shown-empty for a
    // type that cannot carry one); the React state underneath kept the typed
    // value and would reappear -- and be resubmitted -- if the operator
    // switched back to SRT without retyping anything.
    render(
      <SourceEditForm
        source={source({
          source_type: 'srt',
          endpoint_url: 'srt://0.0.0.0:9000?mode=listener',
          credentials_handle: 'old-handle',
          credentials_supported: true,
          credentials_unsupported_reason: null,
        })}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    const credentialField = screen.getByLabelText('Stored credential') as HTMLInputElement
    expect(credentialField.value).toBe('old-handle')
    fireEvent.change(credentialField, { target: { value: 'new-handle-typed-by-mistake' } })
    expect(credentialField.value).toBe('new-handle-typed-by-mistake')

    fireEvent.change(screen.getByLabelText('Source type'), { target: { value: 'rtmp' } })
    const disabledField = screen.getByLabelText('Stored credential') as HTMLInputElement
    expect(disabledField.disabled).toBe(true)
    expect(disabledField.value).toBe('')

    fireEvent.change(screen.getByLabelText('Source type'), { target: { value: 'srt' } })
    const restoredField = screen.getByLabelText('Stored credential') as HTMLInputElement
    expect(restoredField.disabled).toBe(false)
    // The typed value must be gone, not merely hidden -- this is the state,
    // not the display.
    expect(restoredField.value).toBe('')
  })

  it('shows what the server now has next to a field that conflicts, without touching the typed value (reviewer N2)', () => {
    const original = source({ name: 'Council Cam', endpoint_url: 'rtmp://127.0.0.1/live/a' })
    render(
      <SourceEditForm
        source={original}
        conflict={source({
          name: 'Council Cam',
          endpoint_url: 'rtmp://127.0.0.1/live/b',
        })}
        onCancel={vi.fn()}
        onSave={vi.fn()}
      />,
    )

    // The name matches on both sides -- no comparison line for it.
    expect(screen.queryByText(/Server now has: Council Cam/)).toBeNull()
    // The endpoint conflicts -- shown for comparison, form field unchanged.
    expect(screen.getByText('Server now has: rtmp://127.0.0.1/live/b')).not.toBeNull()
    expect((screen.getByLabelText('Stream address') as HTMLInputElement).value).toBe(
      'rtmp://127.0.0.1/live/a',
    )
    expect(screen.getByText(/Someone else saved a change to this source first/i)).not.toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Full-screen integration (hostile-review fixes, WP-07)
// ---------------------------------------------------------------------------

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as unknown as StaffIdentityResponse
}

const SAFE_REPORT = {
  safe_to_broadcast: 'green',
  operator_message: 'All checks passed.',
  resident_preview: { public_url: 'https://example.test/watch' },
} as unknown as SystemHealthReport

const EMPTY_INGEST_PLAN = {
  relay_paths: [],
  local_default: {
    path_id: 'gov-ch12:local',
    label: 'Local RTMP (legacy placeholder)',
    mode: 'local_rtmp',
    endpoint_url: 'rtmp://127.0.0.1/live/civiccast',
    enabled: false,
    health_state: 'not_configured',
    outbound_only: false,
    requires_inbound_firewall: false,
    operator_action: 'Configure a real source.',
  },
  recommended_path_id: 'gov-ch12:local',
} as unknown as LiveIngestPlan

function renderLiveRoomScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <LiveRoomScreen />
    </QueryClientProvider>,
  )
}

function stubCommonQueries() {
  vi.mocked(listChannelProfiles).mockResolvedValue([] as unknown as ChannelProfile[])
  vi.mocked(getSourceSetup).mockResolvedValue({} as unknown as SourceSetupReport)
  vi.mocked(listRecordingTargets).mockResolvedValue([])
  vi.mocked(getLiveIngestPlan).mockResolvedValue(EMPTY_INGEST_PLAN)
  vi.mocked(getSafeToBroadcast).mockResolvedValue(SAFE_REPORT)
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
  stubCommonQueries()
})

describe('LiveRoomScreen probe-button role gate (finding: Probe button rendered for everyone)', () => {
  it('hides Check source from an identity with neither meeting_operator nor setup_admin, and says why', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    vi.mocked(listLiveSources).mockResolvedValue([source({ name: 'Council Cam' })])

    renderLiveRoomScreen()

    // "Council Cam" renders more than once on screen (the source-switcher
    // radio label, the on-air preview copy) -- wait for the unambiguous
    // radio option instead of the plain text.
    await screen.findByRole('radio', { name: /Council Cam/i })
    expect(screen.queryByRole('button', { name: 'Check source' })).toBeNull()
    expect(
      screen.getByText(/needs the meeting operator or setup admin role/i),
    ).not.toBeNull()
  })

  it('shows Check source to a meeting operator (the backend-gate role)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(listLiveSources).mockResolvedValue([source({ name: 'Council Cam' })])

    renderLiveRoomScreen()

    expect(await screen.findByRole('button', { name: 'Check source' })).not.toBeNull()
  })

  it('shows Check source to a setup admin too (the backend accepts either role)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(listLiveSources).mockResolvedValue([source({ name: 'Council Cam' })])

    renderLiveRoomScreen()

    expect(await screen.findByRole('button', { name: 'Check source' })).not.toBeNull()
  })
})

describe('LiveRoomScreen readiness poll (finding: sourcesQuery never re-fetches)', () => {
  it('re-fetches live sources on its own, at most every 10s, and the stale-pill text on screen actually flips (reviewer N3/N4)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    // First fetch: freshly checked and delivering. Second (and every later)
    // fetch: the same source has aged past the readiness TTL. A call-count
    // assertion alone would pass even if the poll fired but the new data
    // never reached the screen -- asserting the rendered chip text actually
    // flips is what proves the fix closes reviewer N3 (the refetch must be
    // visible, not just observable on the mock).
    vi.mocked(listLiveSources)
      .mockResolvedValueOnce([
        source({
          name: 'Council Cam',
          readiness: 'ready',
          probe_state: 'ready',
          observation_age_seconds: 5,
        }),
      ])
      .mockResolvedValue([
        source({
          name: 'Council Cam',
          readiness: 'stale',
          probe_state: 'ready',
          observation_age_seconds: 900,
        }),
      ])

    renderLiveRoomScreen()

    // Let the initial fetch (and whatever render settling it triggers) land
    // before capturing the baseline call count -- with `shouldAdvanceTime`,
    // real wall-clock time elapsing during that settle already counts toward
    // the fake clock, so asserting an exact call count here is not reliable.
    await screen.findByRole('radio', { name: /Council Cam/i })
    expect(screen.getAllByText('Delivering').length).toBeGreaterThan(0)
    const before = vi.mocked(listLiveSources).mock.calls.length

    // The interval this asserts (10_100ms > 10s) must agree with the
    // component's actual refetchInterval and with this test's own name --
    // reviewer N4 caught a prior 8s/10s/"10s" three-way mismatch between the
    // code, its comment, and this test.
    await act(async () => {
      vi.advanceTimersByTime(10_100)
    })

    await waitFor(() =>
      expect(vi.mocked(listLiveSources).mock.calls.length).toBeGreaterThan(before),
    )
    await waitFor(() => expect(screen.getAllByText('Needs re-check').length).toBeGreaterThan(0))
    expect(screen.queryByText('Delivering')).toBeNull()
    vi.useRealTimers()
  })
})

describe('LiveRoomScreen edit-conflict reload (finding: 409 resends the same stale row_version forever)', () => {
  it('on 409, keeps the operator\'s typed edit, shows what the server now has, and the retry carries the fresh row_version (reviewer N2)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const original = source({ name: 'Council Cam', row_version: 1 })
    vi.mocked(listLiveSources).mockResolvedValue([original])
    vi.mocked(updateLiveSource)
      .mockRejectedValueOnce(new ApiError('Request failed: 409 Conflict', 409, 'row changed'))
      .mockResolvedValueOnce(
        source({ name: 'Chamber Cam', row_version: 3, live_source_id: 'sample-source' }),
      )
    const reloaded = source({
      name: 'Council Cam',
      row_version: 2,
      endpoint_url: 'rtmp://127.0.0.1/live/reloaded',
    })
    vi.mocked(getLiveSourceById).mockResolvedValue(reloaded)

    renderLiveRoomScreen()

    // "Council Cam" renders more than once on screen (the source-switcher
    // radio label, the on-air preview copy) -- wait for the unambiguous
    // radio option instead of the plain text.
    await screen.findByRole('radio', { name: /Council Cam/i })
    fireEvent.click(screen.getByRole('button', { name: 'Edit source' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Chamber Cam' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save source' }))

    await screen.findByText(/someone else changed this source/i)
    expect(vi.mocked(getLiveSourceById)).toHaveBeenCalledWith('sample-source')

    // The operator's typed edit survives the 409 -- it is NOT replaced with
    // whatever the server now has. Discarding it was the exact bug this
    // fixes: an earlier version remounted the form on the fresh row here,
    // silently losing "Chamber Cam".
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Chamber Cam')
    // The endpoint was never touched by the operator, so it still reads the
    // ORIGINAL value they loaded -- not the reloaded row's value either.
    expect((screen.getByLabelText('Stream address') as HTMLInputElement).value).toBe(
      original.endpoint_url,
    )
    // What conflicted is shown for comparison instead.
    expect(screen.getByText(`Server now has: ${reloaded.endpoint_url}`)).not.toBeNull()

    // Retrying the save must carry the fresh row_version (2), not the
    // original stale one (1) that just 409'd -- resending the stale version
    // would just 409 again forever.
    fireEvent.click(screen.getByRole('button', { name: 'Save source' }))
    await waitFor(() => expect(vi.mocked(updateLiveSource)).toHaveBeenCalledTimes(2))
    expect(vi.mocked(updateLiveSource).mock.calls[1]).toEqual([
      'sample-source',
      { name: 'Chamber Cam', expected_row_version: 2 },
    ])
  })
})
