import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

import type { ControlRoomReadinessReport, ProductionDevice, TimelineCue } from '../types/api.generated'
import { CueForm, DeviceForm } from './ControlRoomSetupScreen'

const DEVICE: ProductionDevice = {
  device_id: 'dev_obs', label: 'Studio OBS', kind: 'obs', transport: 'websocket',
  host: null, port: null, enabled: true, notes: null, secret_ref: null,
  created_at: 'x', updated_at: 'x',
}

const CUE: TimelineCue = {
  cue_id: 'cue_1',
  surface_id: 'srf',
  label: 'Take CAM2',
  device_id: 'dev_obs',
  action: 'scene',
  payload: { scene: 'CAM2' },
  bank: 0,
  position: 0,
  confirm_required: true,
  proof_boundary: 'Cue fixture for setup tests.',
  created_at: 'x',
}

describe('DeviceForm', () => {
  it('submits the device with a write-only secret', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(<DeviceForm submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Device label'), { target: { value: 'Studio OBS' } })
    fireEvent.change(getByLabelText('Device secret'), { target: { value: 'hunter2' } })
    fireEvent.click(getByText('Register device'))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.label).toBe('Studio OBS')
    expect(payload.kind).toBe('obs')
    expect(payload.secret).toBe('hunter2')
  })

  it('disables submit until a label is entered', () => {
    const { getByText } = render(<DeviceForm submitting={false} onSubmit={vi.fn()} />)
    expect((getByText('Register device') as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('CueForm', () => {
  it('blocks an invalid JSON payload and does not submit', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(<CueForm devices={[DEVICE]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Cue label'), { target: { value: 'Take CAM2' } })
    fireEvent.change(getByLabelText('Cue payload'), { target: { value: '{bad json' } })
    fireEvent.click(getByText('Add cue'))
    const payload = getByLabelText('Cue payload') as HTMLTextAreaElement
    const error = getByText('Payload must be valid JSON.')
    expect(error.getAttribute('role')).toBe('alert')
    expect(payload.getAttribute('aria-invalid')).toBe('true')
    expect(payload.getAttribute('aria-describedby')).toBe(error.getAttribute('id'))
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('authors a gap-8 router_take cue with a parsed payload', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(<CueForm devices={[DEVICE]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Cue label'), { target: { value: 'Router take 3->1' } })
    fireEvent.change(getByLabelText('Cue action'), { target: { value: 'router_take' } })
    fireEvent.change(getByLabelText('Cue payload'), { target: { value: '{"source":"3","destination":"1"}' } })
    fireEvent.click(getByText('Add cue'))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.action).toBe('router_take')
    expect(payload.payload).toEqual({ source: '3', destination: '1' })
  })

  it('uses safe action templates and does not expose input rename as a cue', () => {
    const onSubmit = vi.fn()
    const { getByLabelText, getByText } = render(<CueForm devices={[DEVICE]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Cue label'), { target: { value: 'Take input 2' } })
    fireEvent.change(getByLabelText('Cue action'), { target: { value: 'input' } })
    const payload = getByLabelText('Cue payload') as HTMLTextAreaElement
    expect(payload.value).toContain('"input"')
    expect(payload.value).not.toContain('rename')
    fireEvent.click(getByText('Add cue'))
    expect(onSubmit.mock.calls[0][0].payload).toEqual({ input: 'Camera 1' })
  })

  it('selects the first device when devices arrive after the form mounted', () => {
    const onSubmit = vi.fn()
    const { getByLabelText, getByText, rerender } = render(<CueForm devices={[]} submitting={false} onSubmit={onSubmit} />)

    rerender(<CueForm devices={[DEVICE]} submitting={false} onSubmit={onSubmit} />)
    fireEvent.change(getByLabelText('Cue label'), { target: { value: 'Take CAM2' } })
    fireEvent.click(getByText('Add cue'))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0].device_id).toBe('dev_obs')
  })
})

// --- container role gate -----------------------------------------------------

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getStaffIdentity: vi.fn(),
  getControlRoomReadiness: vi.fn(),
  listProductionDevices: vi.fn(),
  listControlSurfaces: vi.fn(),
  getControlSurface: vi.fn(),
  createProductionDevice: vi.fn(),
  deleteProductionDevice: vi.fn(),
  upsertDeviceProfile: vi.fn(),
  createControlSurface: vi.fn(),
  createTimelineCue: vi.fn(),
  deleteTimelineCue: vi.fn(),
  probeProductionDevice: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import {
  createControlSurface,
  createProductionDevice,
  deleteProductionDevice,
  deleteTimelineCue,
  getControlSurface,
  getControlRoomReadiness,
  getStaffIdentity,
  listControlSurfaces,
  listProductionDevices,
  probeProductionDevice,
} from '../api/client'
import { ControlRoomSetupScreen } from './ControlRoomSetupScreen'

function identity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op', operator_display_name: 'Op', roles }
}

function readinessReport(): ControlRoomReadinessReport {
  return {
    generated_at: '2026-06-30T12:00:00Z',
    ready_for_on_air: true,
    station_device_ready: false,
    summary: 'Control-room configuration is ready for local On-Air dry runs.',
    devices_configured: 1,
    devices_enabled: 1,
    devices_missing_profile: [],
    surfaces_configured: 1,
    cues_configured: 1,
    open_sessions: 0,
    open_on_air_sessions: 0,
    checks: [],
    lpm_profiles: [],
    proof_boundary: 'Readiness is not station-device evidence.',
  }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ControlRoomSetupScreen />
    </QueryClientProvider>,
  )
}

describe('ControlRoomSetupScreen container role gate', () => {
  it('shows an access note for a non-setup-admin', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin role/)).toBeTruthy()
  })

  it('lets a setup admin author devices', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    const { findByText, findByLabelText } = renderScreen()
    expect(await findByText('Control-room readiness')).toBeTruthy()
    expect(await findByText('Equipment check pending')).toBeTruthy()
    expect(await findByLabelText('Device label')).toBeTruthy()
  })

  it('refreshes readiness after a setup mutation changes inventory', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(createProductionDevice).mockResolvedValue(DEVICE)
    const { findByLabelText, findByText } = renderScreen()

    fireEvent.change(await findByLabelText('Device label'), { target: { value: 'Studio OBS' } })
    fireEvent.click(await findByText('Register device'))

    await waitFor(() => expect(createProductionDevice).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(getControlRoomReadiness).toHaveBeenCalledTimes(2))
  })

  it('lets setup admin test a device connection from inventory', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(probeProductionDevice).mockResolvedValue({ reachable: true, detail: 'OBS websocket 5.x ready.' })
    const { findByText } = renderScreen()

    fireEvent.click(await findByText('Test connection'))

    await waitFor(() => expect(probeProductionDevice).toHaveBeenCalledWith('dev_obs'))
    expect(await findByText('Reachable')).toBeTruthy()
    expect(await findByText('OBS websocket 5.x ready.')).toBeTruthy()
  })

  it('shows the persisted device health badge from the device inventory', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([
      { ...DEVICE, last_reachable: true, last_probed_at: new Date().toISOString() },
    ])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    const { findByText } = renderScreen()

    expect(await findByText('Health: Healthy')).toBeTruthy()
  })

  it('shows an unreachable result without inflating readiness when a device probe fails closed', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(probeProductionDevice).mockResolvedValue({
      reachable: false,
      detail: 'OBS websocket is not reachable at 127.0.0.1:4455.',
    })
    const { findByText } = renderScreen()

    fireEvent.click(await findByText('Test connection'))

    await waitFor(() => expect(probeProductionDevice).toHaveBeenCalledWith('dev_obs'))
    expect(await findByText('Unreachable')).toBeTruthy()
    expect(await findByText('OBS websocket is not reachable at 127.0.0.1:4455.')).toBeTruthy()
    expect(getControlRoomReadiness).toHaveBeenCalledTimes(1)
  })

  it('shows the rejected probe error detail', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(probeProductionDevice).mockRejectedValue(new Error('TSR control service unavailable.'))
    const { findByText } = renderScreen()

    fireEvent.click(await findByText('Test connection'))

    await waitFor(() => expect(probeProductionDevice).toHaveBeenCalledWith('dev_obs'))
    expect(await findByText('Unreachable')).toBeTruthy()
    expect(await findByText('TSR control service unavailable.')).toBeTruthy()
  })

  it('shows device query errors instead of a normal empty state', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockRejectedValue(new Error('Device API down.'))
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    const { findByText, queryByText } = renderScreen()

    expect(await findByText(/Could not load production devices/)).toBeTruthy()
    expect(await findByText(/Device API down/)).toBeTruthy()
    expect(queryByText('No devices yet.')).toBeNull()
  })

  it('requires confirmation before removing a device', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(deleteProductionDevice).mockResolvedValue(undefined)
    const { findByText } = renderScreen()

    fireEvent.click(await findByText('Remove'))
    expect(deleteProductionDevice).not.toHaveBeenCalled()
    expect(await findByText(/Confirm remove Studio OBS/)).toBeTruthy()
    fireEvent.click(await findByText('Confirm remove'))

    await waitFor(() => expect(deleteProductionDevice).toHaveBeenCalledWith('dev_obs'))
  })

  it('keeps a new surface label when create fails', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([])
    vi.mocked(listControlSurfaces).mockResolvedValue([])
    vi.mocked(createControlSurface).mockRejectedValue(new Error('Surface API down.'))
    const { findByLabelText, findByText } = renderScreen()

    const input = await findByLabelText('New surface label') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Studio surface' } })
    fireEvent.click(await findByText('Create surface'))

    expect(await findByText('Surface API down.')).toBeTruthy()
    expect(input.value).toBe('Studio surface')
  })

  it('requires confirmation before deleting a cue', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([DEVICE])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [CUE],
    })
    vi.mocked(deleteTimelineCue).mockResolvedValue(undefined)
    const { findByLabelText, findByText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Edit surface'), { target: { value: 'srf' } })
    expect(await findByText('Take CAM2')).toBeTruthy()
    fireEvent.click(await findByText('Delete'))
    expect(deleteTimelineCue).not.toHaveBeenCalled()
    expect(await findByText('Confirm delete?')).toBeTruthy()
    fireEvent.click(await findByText('Confirm delete'))

    await waitFor(() => expect(deleteTimelineCue).toHaveBeenCalledWith('cue_1'))
  })

  it('explains that a production device is required before cue authoring', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getControlRoomReadiness).mockResolvedValue(readinessReport())
    vi.mocked(listProductionDevices).mockResolvedValue([])
    vi.mocked(listControlSurfaces).mockResolvedValue([
      { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
    ])
    vi.mocked(getControlSurface).mockResolvedValue({
      surface: { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'op', created_at: 'x', updated_at: 'x' },
      cues: [],
    })
    const { findByLabelText, findByText, queryByLabelText } = renderScreen()

    await findByText('Chamber')
    fireEvent.change(await findByLabelText('Edit surface'), { target: { value: 'srf' } })

    expect(await findByText('Register a production device before adding cues to this surface.')).toBeTruthy()
    expect(queryByLabelText('Cue device')).toBeNull()
  })
})
