import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  downloadReportsExport,
  fireControlRoomCue,
  getControlRoomReadiness,
  getStationSetupState,
  uploadAssetFile,
} from './client'

describe('rehearsal media upload', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  it('marks a local test clip as the exact private-rehearsal sample', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ asset_id: 'test-clip' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await uploadAssetFile({
      assetId: 'test-clip',
      title: 'Test clip',
      file: new File(['video'], 'test clip.mp4', { type: 'video/mp4' }),
      selectForRehearsal: true,
    })

    const request = fetchMock.mock.calls[0]![1]!
    const body = request.body as FormData
    expect(body.get('select_for_rehearsal')).toBe('true')
    expect(body.get('asset_id')).toBe('test-clip')
    expect(body.get('file')).toBeInstanceOf(File)
  })
})

describe('staff authentication throttling', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  it('preserves Retry-After as an actionable duration', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'bad-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({ detail: 'Too many failed staff authentication attempts. Wait and retry.' }),
          {
            status: 429,
            headers: { 'Content-Type': 'application/json', 'Retry-After': '37' },
          },
        ),
      ),
    )

    await expect(getControlRoomReadiness()).rejects.toMatchObject({
      status: 429,
      retryAfterSeconds: 37,
      detail: 'Too many unsuccessful sign-in attempts from this network. Wait 37 seconds, then try again.',
    } satisfies Partial<ApiError>)
  })

  it('uses singular copy for a one-second Retry-After', () => {
    const error = new ApiError(
      'request failed',
      429,
      'Too many failed staff authentication attempts. Wait and retry.',
      undefined,
      1,
    )

    expect(error.detail).toBe(
      'Too many unsuccessful sign-in attempts from this network. Wait 1 second, then try again.',
    )
  })
})

describe('setup nonce handoff', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('prefers the installer URL nonce over a stale stored nonce', async () => {
    window.history.replaceState(null, '', '/operator/?nonce=fresh-installer-nonce#/setup')
    window.sessionStorage.setItem('civiccast.setupNonce', 'stale-nonce')
    const fetchMock = vi.fn(async () => (
      new Response(JSON.stringify({ setup_complete: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    ))
    vi.stubGlobal('fetch', fetchMock)

    await getStationSetupState()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/setup/station-state',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-CivicCast-Setup-Nonce': 'fresh-installer-nonce',
        }),
      }),
    )
    expect(window.sessionStorage.getItem('civiccast.setupNonce')).toBe('fresh-installer-nonce')
  })
})

describe('authenticated staff downloads', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('attaches the staff bearer token to report exports', async () => {
    window.history.replaceState(null, '', '/operator/#/reports')
    window.localStorage.setItem('civiccast.staffToken', 'staff-token')
    const fetchMock = vi.fn(async () => new Response('asset_id,title\n', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await downloadReportsExport({
      type: 'shows',
      format: 'csv',
      from: '2026-06-01T00:00:00Z',
      to: '2026-06-02T00:00:00Z',
      channel: 'public',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/staff/reports/export?from=2026-06-01T00%3A00%3A00Z&to=2026-06-02T00%3A00%3A00Z&channel=public&type=shows&format=csv',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer staff-token',
        }),
      }),
    )
  })
})

describe('control-room live fire client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('sends the dry-run material fingerprint with the fire request', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'staff-token')
    const fetchMock = vi.fn(async () => (
      new Response(JSON.stringify({
        event_id: 'e1',
        session_id: 's1',
        cue_id: 'c1',
        operator_id: 'op',
        device_id: 'dev',
        action: 'scene',
        result: 'fired',
        fired_at: '2026-01-01T00:00:00Z',
        detail: {},
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    ))
    vi.stubGlobal('fetch', fetchMock)

    await fireControlRoomCue('s1', 'c1', { material_state_fingerprint: 'abc123' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/staff/control-room/sessions/s1/cues/c1/fire',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ material_state_fingerprint: 'abc123' }),
        headers: expect.objectContaining({
          Authorization: 'Bearer staff-token',
        }),
      }),
    )
  })

  it('fetches the control-room readiness report with the staff token', async () => {
    window.localStorage.setItem('civiccast.staffToken', 'staff-token')
    const fetchMock = vi.fn(async () => (
      new Response(JSON.stringify({
        generated_at: '2026-06-30T12:00:00Z',
        ready_for_on_air: false,
        station_device_ready: false,
        summary: 'Control-room configuration has blockers before On-Air use.',
        devices_configured: 0,
        devices_enabled: 0,
        devices_missing_profile: [],
        surfaces_configured: 0,
        cues_configured: 0,
        open_sessions: 0,
        open_on_air_sessions: 0,
        checks: [],
        lpm_profiles: [],
        proof_boundary: 'Readiness is not station-device evidence.',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    ))
    vi.stubGlobal('fetch', fetchMock)

    await getControlRoomReadiness()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/staff/control-room/readiness',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer staff-token',
        }),
      }),
    )
  })
})
