import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

import type {
  ControlRoomReadinessReport,
  ControlRoomSession,
  CueFiredEvent,
  CuePlan,
  ProductionDevice,
  TimelineCue,
} from '../types/api.generated'
import {
  ControlRoomSupportBundlePanel,
  CueButton,
  CuePlanPreview,
  DeviceStrip,
  ProgramFeedBanner,
  SafeStatePanel,
  SessionModeBanner,
  SessionAuditDrawer,
} from './ControlRoomScreen'

const DEVICE: ProductionDevice = {
  device_id: 'dev_obs', label: 'Studio OBS', kind: 'obs', transport: 'websocket',
  host: '127.0.0.1', port: 4455, enabled: true, notes: null, secret_ref: null,
  last_probed_at: null, last_reachable: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const PLAN: CuePlan = {
  cue_id: 'cue_1', surface_id: 'srf', device_id: 'dev_obs', label: 'Take CAM2', action: 'scene',
  resolved_payload: { scene: 'CAM2' }, command_preview: 'Studio OBS: set scene -> CAM2',
  ready_to_send: true, confirm_required: true, take_delay_ms: 120, post_roll_ms: 0,
  material_state_fingerprint: 'abc123def456abc123def456abc123def456abc123def456abc123def456abcd',
  operator_action: 'fire to send', proof_boundary: 'Cue plan preview only; no device socket is opened by this API.',
}

const CUE: TimelineCue = {
  cue_id: 'cue_1', surface_id: 'srf', label: 'Take CAM2', device_id: 'dev_obs', action: 'scene',
  payload: { scene: 'CAM2' }, confirm_required: true, bank: 0, position: 0,
  proof_boundary: 'x', created_at: '2026-01-01T00:00:00Z',
}

// --- sub-components ----------------------------------------------------------

describe('DeviceStrip', () => {
  it('shows reachability and a probe button when canProbe', () => {
    const onProbe = vi.fn()
    const { getByText } = render(
      <DeviceStrip devices={[DEVICE]} reach={{ dev_obs: false }} canProbe probingId={null} onProbe={onProbe} />,
    )
    expect(getByText('Unreachable')).toBeTruthy()
    fireEvent.click(getByText('Probe'))
    expect(onProbe).toHaveBeenCalledWith('dev_obs')
  })

  it('hides the probe button when canProbe is false', () => {
    const { queryByText, getByText } = render(
      <DeviceStrip devices={[DEVICE]} reach={{}} canProbe={false} probingId={null} onProbe={vi.fn()} />,
    )
    expect(getByText('Not probed')).toBeTruthy()
    expect(queryByText('Probe')).toBeNull()
  })

  it('shows the persisted health badge before this session probes the device', () => {
    const healthy: ProductionDevice = {
      ...DEVICE,
      last_reachable: true,
      last_probed_at: new Date().toISOString(),
    }
    const { getByText } = render(
      <DeviceStrip devices={[healthy]} reach={{}} canProbe={false} probingId={null} onProbe={vi.fn()} />,
    )
    expect(getByText('Healthy')).toBeTruthy()
  })

  it('flags a stale health reading instead of trusting an old probe forever', () => {
    const stale: ProductionDevice = {
      ...DEVICE,
      last_reachable: true,
      last_probed_at: new Date(Date.now() - 400_000).toISOString(), // > 300s threshold
    }
    const { getByText } = render(
      <DeviceStrip devices={[stale]} reach={{}} canProbe={false} probingId={null} onProbe={vi.fn()} />,
    )
    expect(getByText('Stale — probe again')).toBeTruthy()
  })

  it('hides the persisted health badge once this session has its own probe result', () => {
    const { queryByText } = render(
      <DeviceStrip devices={[DEVICE]} reach={{ dev_obs: true }} canProbe={false} probingId={null} onProbe={vi.fn()} />,
    )
    expect(queryByText('Never probed')).toBeNull()
  })
})

describe('CuePlanPreview', () => {
  it('shows the resolved command preview, timing, and proof boundary', () => {
    const { getByText } = render(<CuePlanPreview plan={PLAN} />)
    expect(getByText('Studio OBS: set scene -> CAM2')).toBeTruthy()
    expect(getByText('Ready to send')).toBeTruthy()
    expect(getByText('dry-run abc123def456')).toBeTruthy()
    expect(getByText('Next: fire to send')).toBeTruthy()
    expect(getByText(/no device socket is opened/)).toBeTruthy()
    expect(getByText(/take-delay 120ms/)).toBeTruthy()
  })
})

describe('CueButton', () => {
  it('requires a two-step confirm for a confirm_required cue', () => {
    const onFire = vi.fn()
    const onConfirmToggle = vi.fn()
    const { getByText, rerender } = render(
      <CueButton cue={CUE} canFire planned={PLAN} busy={false} confirming={false}
        sessionMode="on_air" onPlan={vi.fn()} onFire={onFire} onConfirmToggle={onConfirmToggle} />,
    )
    // first the operator must arm the confirm — no direct fire
    fireEvent.click(getByText(/Fire\.\.\. \(needs confirm\)/))
    expect(onConfirmToggle).toHaveBeenCalledWith(true)
    expect(onFire).not.toHaveBeenCalled()
    // once confirming, the real Fire button appears
    rerender(
      <CueButton cue={CUE} canFire planned={PLAN} busy={false} confirming
        sessionMode="on_air" onPlan={vi.fn()} onFire={onFire} onConfirmToggle={onConfirmToggle} />,
    )
    fireEvent.click(getByText('Confirm fire'))
    expect(onFire).toHaveBeenCalled()
  })
})

describe('SafeStatePanel', () => {
  const session: ControlRoomSession = {
    session_id: 's', surface_id: 'srf', operator_id: 'op', operator_name: 'Op',
    program_feed_source_ref: 'public:control-room', mode: 'on_air', safe_state_cue_id: 'cue_1',
    state: 'open', started_at: '2026-01-01T00:00:00Z', on_air_expires_at: '2026-01-01T00:30:00Z', ended_at: null,
  }

  it('requires a dry run before the safe-state action can fire', () => {
    const onPlan = vi.fn()
    const onFire = vi.fn()
    const { getByText, rerender } = render(
      <SafeStatePanel session={session} cues={[CUE]} planned={null} busy={false} onPlan={onPlan} onFire={onFire} />,
    )
    const run = getByText('Panic: Run Safe State') as HTMLButtonElement
    expect(run.disabled).toBe(true)
    fireEvent.click(getByText('Dry Run Safe State'))
    expect(onPlan).toHaveBeenCalledWith('cue_1')

    rerender(<SafeStatePanel session={session} cues={[CUE]} planned={PLAN} busy={false} onPlan={onPlan} onFire={onFire} />)
    fireEvent.click(getByText('Panic: Run Safe State'))
    expect(onFire).toHaveBeenCalledWith('cue_1')
  })

  it('keeps the safe-state action disabled when the dry run is not ready', () => {
    const notReadyPlan: CuePlan = { ...PLAN, ready_to_send: false, operator_action: 'Fix device state first.' }
    const onFire = vi.fn()
    const { getByText } = render(
      <SafeStatePanel session={session} cues={[CUE]} planned={notReadyPlan} busy={false}
        onPlan={vi.fn()} onFire={onFire} />,
    )
    const run = getByText('Panic: Run Safe State') as HTMLButtonElement
    expect(run.disabled).toBe(true)
    fireEvent.click(run)
    expect(onFire).not.toHaveBeenCalled()
  })

  it('surfaces safe-state dry-run failures inline', () => {
    const { getByText } = render(
      <SafeStatePanel session={session} cues={[CUE]} planned={null} busy={false}
        planError="Safe State dry run failed: TSR control service unavailable."
        onPlan={vi.fn()} onFire={vi.fn()} />,
    )
    expect(getByText('Safe State dry run failed: TSR control service unavailable.')).toBeTruthy()
  })

  it('uses operator-facing copy for the dry-run precondition', () => {
    const { getByText } = render(
      <SafeStatePanel session={session} cues={[CUE]} planned={null} busy={false}
        onPlan={vi.fn()} onFire={vi.fn()} />,
    )
    expect(getByText(/Dry Run checks the current device and cue state/)).toBeTruthy()
  })
})

describe('ProgramFeedBanner', () => {
  it('shows the feed and the read-only S5 boundary note', () => {
    const session: ControlRoomSession = {
      session_id: 's', surface_id: 'srf', operator_id: 'op', operator_name: 'Op',
      program_feed_source_ref: 'public:control-room', mode: 'test', safe_state_cue_id: null,
      state: 'open', started_at: '2026-01-01T00:00:00Z', on_air_expires_at: null, ended_at: null,
    }
    const { getByText } = render(<ProgramFeedBanner session={session} />)
    expect(getByText(/public:control-room/)).toBeTruthy()
    expect(getByText(/Playout \(S5\) action/)).toBeTruthy()
  })
})

describe('SessionModeBanner', () => {
  it('makes test mode unambiguous', () => {
    const session: ControlRoomSession = {
      session_id: 's', surface_id: 'srf', operator_id: 'op', operator_name: 'Op',
      program_feed_source_ref: 'public:control-room', mode: 'test', safe_state_cue_id: null,
      state: 'open', started_at: '2026-01-01T00:00:00Z', on_air_expires_at: null, ended_at: null,
    }
    const { getByText } = render(<SessionModeBanner session={session} />)
    expect(getByText(/TEST MODE - device actions are blocked/)).toBeTruthy()
  })
})

describe('SessionAuditDrawer', () => {
  it('lists fired cues newest-shown', () => {
    const events: CueFiredEvent[] = [{
      event_id: 'e1', session_id: 's', cue_id: 'cue_1', operator_id: 'op', device_id: 'dev_obs',
      action: 'scene', result: 'fired', fired_at: '2026-01-01T00:00:00Z', detail: {},
    }]
    const { getByText } = render(<SessionAuditDrawer events={events} />)
    expect(getByText('Fired')).toBeTruthy()
    expect(getByText('Take scene')).toBeTruthy()
  })
})

describe('ControlRoomSupportBundlePanel', () => {
  it('creates a redacted support bundle with the operator note and displays contents', async () => {
    vi.mocked(createSupportBundle).mockResolvedValue({
      bundle_id: 'bundle_1',
      generated_at: '2026-01-01T00:00:00Z',
      path: 'C:\\CivicCast\\support\\bundle.zip',
      sha256: 'a'.repeat(64),
      redacted: true,
      contains: ['alerts.json', 'egress.json'],
      excludes: ['secrets'],
      next_step: 'Attach this bundle to support.',
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { getByLabelText, getByText, findByText } = render(
      <QueryClientProvider client={client}>
        <ControlRoomSupportBundlePanel canCreate />
      </QueryClientProvider>,
    )
    fireEvent.change(getByLabelText('Control-room support note'), { target: { value: 'OBS scene mismatch' } })
    fireEvent.click(getByText('Create support bundle'))
    await waitFor(() => expect(createSupportBundle).toHaveBeenCalledWith({
      operator_note: 'Production Control Room note: OBS scene mismatch',
    }))
    expect(await findByText('Support bundle ready')).toBeTruthy()
    expect(await findByText('alerts.json, egress.json')).toBeTruthy()
    expect(await findByText('secrets')).toBeTruthy()
  })

  it('keeps support bundle creation disabled for non-support admins', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { getByText } = render(
      <QueryClientProvider client={client}>
        <ControlRoomSupportBundlePanel canCreate={false} />
      </QueryClientProvider>,
    )
    const button = getByText('Create support bundle') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(getByText('Support bundles require support admin.')).toBeTruthy()
  })

  it('surfaces support bundle errors', async () => {
    vi.mocked(createSupportBundle).mockRejectedValueOnce(new Error('bundle failed'))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { getByText, findByText } = render(
      <QueryClientProvider client={client}>
        <ControlRoomSupportBundlePanel canCreate />
      </QueryClientProvider>,
    )
    fireEvent.click(getByText('Create support bundle'))
    expect(await findByText('bundle failed')).toBeTruthy()
  })
})

// --- container role gate (mocked client) ------------------------------------

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
  getStaffIdentity: vi.fn(),
  getControlRoomReadiness: vi.fn(),
  listProductionDevices: vi.fn(),
  listControlSurfaces: vi.fn(),
  getControlSurface: vi.fn(),
  getControlRoomSessionAudit: vi.fn(),
  openControlRoomSession: vi.fn(),
  closeControlRoomSession: vi.fn(),
  planControlRoomCue: vi.fn(),
  fireControlRoomCue: vi.fn(),
  rollbackControlRoomSession: vi.fn(),
  probeProductionDevice: vi.fn(),
  createSupportBundle: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import {
  createSupportBundle,
  getControlRoomReadiness,
  getControlSurface,
  getStaffIdentity,
  getControlRoomSessionAudit,
  listControlSurfaces,
  listProductionDevices,
  openControlRoomSession,
  planControlRoomCue,
  fireControlRoomCue,
  rollbackControlRoomSession,
} from '../api/client'
import { ControlRoomScreen } from './ControlRoomScreen'

function identity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op', operator_display_name: 'Op', roles }
}

function readinessReport(overrides: Partial<ControlRoomReadinessReport> = {}): ControlRoomReadinessReport {
  return {
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
    ...overrides,
  }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ControlRoomScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ControlRoomScreen container role gate', () => {
  it('shows an access note for an operator without a control-room role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the publish\/meeting operator, setup admin, or\s+support admin role/)).toBeTruthy()
  })

  it('lets a support admin read devices but notes operation is meeting-operator only', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([{ surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' }])
    const { findByText } = renderScreen()
    expect(await findByText('Devices')).toBeTruthy()
    expect(await findByText('Studio OBS')).toBeTruthy()
  })

  it('offers an open-session affordance to a meeting operator on a chosen surface', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      checks: [{
        check_id: 'device-inventory',
        label: 'Device inventory',
        status: 'blocked',
        severity: 'blocker',
        detail: 'No production devices are configured.',
        operator_action: 'Register devices.',
        evidence_ref: 'production_devices',
      }],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([])
    vi.mocked(listControlSurfaces).mockResolvedValue([{ surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' }])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [],
    })
    const { findByText, findByLabelText } = renderScreen()
    expect(await findByText('Control-room readiness')).toBeTruthy()
    expect(await findByText('Equipment check pending')).toBeTruthy()
    const select = await findByLabelText('Control surface')
    await findByText('Chamber') // wait for the surface option to load before selecting it
    fireEvent.change(select, { target: { value: 'srf' } })
    expect(await findByText('Open Test Session')).toBeTruthy()
  })

  it('refreshes readiness after opening a control-room session', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({ cues_configured: 1 }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([{ surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' }])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(openControlRoomSession).mockResolvedValue({
      session_id: 's1',
      surface_id: 'srf',
      operator_id: 'op',
      operator_name: 'Op',
      program_feed_source_ref: null,
      mode: 'test',
      safe_state_cue_id: null,
      state: 'open',
      started_at: '2026-01-01T00:00:00Z',
      on_air_expires_at: null,
      ended_at: null,
    })
    const { findByLabelText, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByText('Open Test Session'))

    await waitFor(() => expect(openControlRoomSession).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getControlRoomReadiness).toHaveBeenCalledTimes(2))
  })

  it('dry-runs and fires the configured safe-state cue with the material fingerprint', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      ready_for_on_air: true,
      summary: 'Control-room configuration is ready.',
      devices_configured: 1,
      devices_enabled: 1,
      surfaces_configured: 1,
      cues_configured: 1,
      checks: [],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(openControlRoomSession).mockResolvedValue({
      session_id: 's1',
      surface_id: 'srf',
      operator_id: 'op',
      operator_name: 'Op',
      program_feed_source_ref: 'public:control-room',
      mode: 'on_air',
      safe_state_cue_id: 'cue_1',
      state: 'open',
      started_at: '2026-01-01T00:00:00Z',
      on_air_expires_at: '2026-01-01T00:30:00Z',
      ended_at: null,
    })
    vi.mocked(getControlRoomSessionAudit).mockResolvedValue([])
    vi.mocked(planControlRoomCue).mockResolvedValue(PLAN)
    vi.mocked(fireControlRoomCue).mockResolvedValue({
      event_id: 'e1',
      session_id: 's1',
      cue_id: 'cue_1',
      operator_id: 'op',
      device_id: 'dev_obs',
      action: 'scene',
      result: 'fired',
      fired_at: '2026-01-01T00:00:01Z',
      detail: {},
    })
    const { findByLabelText, findByRole, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByLabelText('On-Air Mode'))
    await findByRole('button', { name: /Take CAM2/ })
    fireEvent.change(await findByLabelText('Safe-state cue'), { target: { value: 'cue_1' } })
    fireEvent.click(await findByLabelText(/I understand On-Air cue actions/))
    fireEvent.click(await findByText('Open On-Air Session'))

    await waitFor(() => expect(openControlRoomSession).toHaveBeenCalledWith({
      surface_id: 'srf',
      mode: 'on_air',
      safe_state_cue_id: 'cue_1',
      confirm_on_air: true,
    }))
    fireEvent.click(await findByText('Dry Run Safe State'))
    await waitFor(() => expect(planControlRoomCue).toHaveBeenCalledWith('s1', 'cue_1'))
    fireEvent.click(await findByText('Panic: Run Safe State'))
    await waitFor(() => expect(fireControlRoomCue).toHaveBeenCalledWith('s1', 'cue_1', {
      material_state_fingerprint: PLAN.material_state_fingerprint,
    }))
  })

  it('offers a rollback to safe state when a cue fails to fire on-air, and fires it', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      ready_for_on_air: true,
      summary: 'Control-room configuration is ready.',
      devices_configured: 1,
      devices_enabled: 1,
      surfaces_configured: 1,
      cues_configured: 1,
      checks: [],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(openControlRoomSession).mockResolvedValue({
      session_id: 's1',
      surface_id: 'srf',
      operator_id: 'op',
      operator_name: 'Op',
      program_feed_source_ref: 'public:control-room',
      mode: 'on_air',
      safe_state_cue_id: 'cue_1',
      state: 'open',
      started_at: '2026-01-01T00:00:00Z',
      on_air_expires_at: '2026-01-01T00:30:00Z',
      ended_at: null,
    })
    vi.mocked(getControlRoomSessionAudit).mockResolvedValue([])
    vi.mocked(planControlRoomCue).mockResolvedValue(PLAN)
    vi.mocked(fireControlRoomCue).mockRejectedValue(new Error('Production control service error.'))
    vi.mocked(rollbackControlRoomSession).mockResolvedValue({
      event_id: 'e_rollback',
      session_id: 's1',
      cue_id: 'cue_1',
      operator_id: 'op',
      device_id: 'dev_obs',
      action: 'scene',
      result: 'fired',
      fired_at: '2026-01-01T00:00:02Z',
      detail: {},
    })
    const { findByLabelText, findByRole, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByLabelText('On-Air Mode'))
    await findByRole('button', { name: /Take CAM2/ })
    fireEvent.change(await findByLabelText('Safe-state cue'), { target: { value: 'cue_1' } })
    fireEvent.click(await findByLabelText(/I understand On-Air cue actions/))
    fireEvent.click(await findByText('Open On-Air Session'))
    await waitFor(() => expect(openControlRoomSession).toHaveBeenCalledTimes(1))

    fireEvent.click(await findByRole('button', { name: /Take CAM2/ }))
    await waitFor(() => expect(planControlRoomCue).toHaveBeenCalledWith('s1', 'cue_1'))
    fireEvent.click(await findByText(/Fire\.\.\. \(needs confirm\)/))
    fireEvent.click(await findByText('Confirm fire'))
    await waitFor(() => expect(fireControlRoomCue).toHaveBeenCalled())

    fireEvent.click(await findByText('Roll back to Safe State'))
    await waitFor(() => expect(rollbackControlRoomSession).toHaveBeenCalledWith('s1'))
    expect(await findByText('Rolled back to Safe State.')).toBeTruthy()
  })

  it('shows the operator why a safe-state dry run failed', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      ready_for_on_air: true,
      summary: 'Control-room configuration is ready.',
      devices_configured: 1,
      devices_enabled: 1,
      surfaces_configured: 1,
      cues_configured: 1,
      checks: [],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(openControlRoomSession).mockResolvedValue({
      session_id: 's1',
      surface_id: 'srf',
      operator_id: 'op',
      operator_name: 'Op',
      program_feed_source_ref: 'public:control-room',
      mode: 'on_air',
      safe_state_cue_id: 'cue_1',
      state: 'open',
      started_at: '2026-01-01T00:00:00Z',
      on_air_expires_at: '2026-01-01T00:30:00Z',
      ended_at: null,
    })
    vi.mocked(getControlRoomSessionAudit).mockResolvedValue([])
    vi.mocked(planControlRoomCue).mockRejectedValue(new Error('TSR control service unavailable.'))
    const { findByLabelText, findByRole, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByLabelText('On-Air Mode'))
    await findByRole('button', { name: /Take CAM2/ })
    fireEvent.change(await findByLabelText('Safe-state cue'), { target: { value: 'cue_1' } })
    fireEvent.click(await findByLabelText(/I understand On-Air cue actions/))
    fireEvent.click(await findByText('Open On-Air Session'))

    fireEvent.click(await findByText('Dry Run Safe State'))
    expect(await findByText('Safe State dry run failed: TSR control service unavailable.')).toBeTruthy()
  })

  it('blocks On-Air session opening while readiness has blockers', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      checks: [{
        check_id: 'device-profiles',
        label: 'Device profiles',
        status: 'blocked',
        severity: 'blocker',
        detail: 'Device is missing profile.',
        operator_action: 'Save a device profile for every production device.',
        evidence_ref: 'device_profiles',
      }],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    const { findByLabelText, findByRole, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByLabelText('On-Air Mode'))
    await findByRole('button', { name: /Take CAM2/ })
    fireEvent.change(await findByLabelText('Safe-state cue'), { target: { value: 'cue_1' } })
    fireEvent.click(await findByLabelText(/I understand On-Air cue actions/))
    expect(await findByText(/On-Air Session is blocked until readiness passes/)).toBeTruthy()
    expect(await findByText('Needs attention: Control-room readiness')).toBeTruthy()
    expect(await findByText('Ready: Safe-state cue selected')).toBeTruthy()
    expect(await findByText('Ready: On-Air responsibility acknowledged')).toBeTruthy()
    const open = await findByText('Open On-Air Session') as HTMLButtonElement
    expect(open.disabled).toBe(true)
    expect(open.getAttribute('style')).toContain('var(--cc-surface-3)')
    fireEvent.click(open)
    expect(openControlRoomSession).not.toHaveBeenCalled()
  })

  it('shows selected-surface load failures instead of a false empty-cue state', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({ cues_configured: 1 }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockRejectedValue(new Error('Surface API down.'))
    const { findByLabelText, findByText, queryByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })

    expect(await findByText(/Could not load this surface/)).toBeTruthy()
    expect(await findByText(/Surface API down/)).toBeTruthy()
    expect(queryByText('This surface has no cues yet.')).toBeNull()
    expect(queryByText('Open Test Session')).toBeNull()
  })

  it('clears a stale safe-state dry run after a later dry-run failure', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport({
      ready_for_on_air: true,
      summary: 'Control-room configuration is ready.',
      devices_configured: 1,
      devices_enabled: 1,
      surfaces_configured: 1,
      cues_configured: 1,
      checks: [],
    }))
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(openControlRoomSession).mockResolvedValue({
      session_id: 's1',
      surface_id: 'srf',
      operator_id: 'op',
      operator_name: 'Op',
      program_feed_source_ref: 'public:control-room',
      mode: 'on_air',
      safe_state_cue_id: 'cue_1',
      state: 'open',
      started_at: '2026-01-01T00:00:00Z',
      on_air_expires_at: '2026-01-01T00:30:00Z',
      ended_at: null,
    })
    vi.mocked(getControlRoomSessionAudit).mockResolvedValue([])
    vi.mocked(planControlRoomCue)
      .mockResolvedValueOnce(PLAN)
      .mockRejectedValueOnce(new Error('TSR control service unavailable.'))
    const { findByLabelText, findByRole, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Control surface'), { target: { value: 'srf' } })
    fireEvent.click(await findByLabelText('On-Air Mode'))
    await findByRole('button', { name: /Take CAM2/ })
    fireEvent.change(await findByLabelText('Safe-state cue'), { target: { value: 'cue_1' } })
    fireEvent.click(await findByLabelText(/I understand On-Air cue actions/))
    fireEvent.click(await findByText('Open On-Air Session'))

    fireEvent.click(await findByText('Dry Run Safe State'))
    const panic = await findByText('Panic: Run Safe State') as HTMLButtonElement
    await waitFor(() => expect(panic.disabled).toBe(false))

    fireEvent.click(await findByText('Dry Run Safe State'))
    expect(await findByText('Safe State dry run failed: TSR control service unavailable.')).toBeTruthy()
    await waitFor(() => expect(panic.disabled).toBe(true))
    fireEvent.click(panic)
    expect(fireControlRoomCue).not.toHaveBeenCalled()
  })
})
