import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

afterEach(cleanup)

import type { ContributionRoom, RemoteGuestSession, StaffIdentityResponse } from '../types/api.generated'
import {
  CreateRoomForm,
  DiagnosticsView,
  GuestTray,
  InviteComposer,
  RoomRow,
} from './RemoteContributionScreen'
import { hasRole } from './contribution-format'

function identity(overrides: Partial<StaffIdentityResponse> = {}): StaffIdentityResponse {
  return {
    operator_id: 'op_1', operator_display_name: 'Op', token_id: 'tok_1',
    scopes: [], roles: [], ...overrides,
  }
}

describe('hasRole (S17 console role gate)', () => {
  it('grants on DERIVED product roles, not raw token scopes', () => {
    // Regression for the scopes-vs-roles bug that left the whole S17 console
    // dead: real tokens carry scopes like ["operator"]/["admin"], never the
    // product-role names — the gate must read identity.roles.
    expect(hasRole(identity({ roles: ['meeting_operator'] }), ['meeting_operator'])).toBe(true)
    expect(hasRole(identity({ roles: ['setup_admin'] }), ['setup_admin'])).toBe(true)
    // raw scopes alone (the old, broken source) must NOT grant access
    expect(hasRole(identity({ scopes: ['operator'] }), ['meeting_operator'])).toBe(false)
    expect(hasRole(identity({ scopes: ['admin'] }), ['setup_admin'])).toBe(false)
    expect(hasRole(undefined, ['support_admin'])).toBe(false)
  })
})

function guest(overrides: Partial<RemoteGuestSession> = {}): RemoteGuestSession {
  return {
    session_id: 'gs_1', room_id: 'room_1', invite_id: 'inv_1', guest_display_name: 'Jane',
    state: 'connected', connection_quality: 'good', admitted_at: null,
    joined_at: '2026-01-01T00:00:00Z', on_air_at: null, ended_at: null, proof_boundary: 'lab',
    ...overrides,
  }
}

const ROOM: ContributionRoom = {
  room_id: 'room_1', channel_id: 'ch_gov', name: 'Chamber', vdo_room_name: 'vdo_1',
  max_guests: 6, state: 'live', compositor_target: 'gst_compositor',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

describe('GuestTray', () => {
  it('holds an un-admitted guest: shows Admit and disables On air (waiting-room gate)', () => {
    const onAction = vi.fn()
    const { getByText } = render(
      <GuestTray sessions={[guest()]} canOperate pending={false} onAction={onAction} />,
    )
    expect(getByText('In waiting room')).toBeTruthy()
    expect(getByText('Admit')).toBeTruthy()
    const onAir = getByText('On air') as HTMLButtonElement
    expect(onAir.disabled).toBe(true) // cannot air until admitted
    fireEvent.click(getByText('Admit'))
    expect(onAction).toHaveBeenCalledWith('gs_1', 'admit')
  })

  it('enables On air once admitted and fires the action', () => {
    const onAction = vi.fn()
    const admitted = guest({ admitted_at: '2026-01-01T00:01:00Z' })
    const { getByText, queryByText } = render(
      <GuestTray sessions={[admitted]} canOperate pending={false} onAction={onAction} />,
    )
    expect(queryByText('Admit')).toBeNull() // already admitted
    const onAir = getByText('On air') as HTMLButtonElement
    expect(onAir.disabled).toBe(false)
    fireEvent.click(onAir)
    expect(onAction).toHaveBeenCalledWith('gs_1', 'on-air')
  })

  it('hides controls when the operator cannot operate', () => {
    const { queryByText, getByText } = render(
      <GuestTray sessions={[guest()]} canOperate={false} pending={false} onAction={vi.fn()} />,
    )
    expect(getByText('Jane')).toBeTruthy()
    expect(queryByText('Admit')).toBeNull()
    expect(queryByText('Drop')).toBeNull()
  })

  it('omits ended/dropped guests from the active tray', () => {
    const { getByText } = render(
      <GuestTray
        sessions={[guest({ session_id: 'gs_x', state: 'dropped' }), guest({ guest_display_name: 'Ann' })]}
        canOperate pending={false} onAction={vi.fn()}
      />,
    )
    expect(getByText('Guests (1)')).toBeTruthy()
    expect(getByText('Ann')).toBeTruthy()
  })
})

describe('DiagnosticsView', () => {
  it('shows the honest no-compositor banner and warn pills when the tier is down', () => {
    const { getByText } = render(
      <DiagnosticsView diag={{ turn_reachable: false, vdo_process_up: false, coturn_process_up: false, ice_summary: '', detail: 'disabled' }} />,
    )
    expect(getByText('TURN unreachable')).toBeTruthy()
    expect(getByText(/requires a compositor/)).toBeTruthy()
  })

  it('shows healthy pills when everything is up', () => {
    const { getByText, queryByText } = render(
      <DiagnosticsView diag={{ turn_reachable: true, vdo_process_up: true, coturn_process_up: true, ice_summary: 'ok', detail: '' }} />,
    )
    expect(getByText('TURN reachable')).toBeTruthy()
    expect(queryByText(/requires a compositor/)).toBeNull()
  })

  it('reads as commissioned when TURN is reachable with no local coturn process (documented external TURN, PR #9)', () => {
    // Before this fix, coturn_process_up=false always showed the
    // no-compositor warning -- a false negative for the owner-approved
    // "external TURN, no native Windows coturn" posture.
    const { getByText, queryByText } = render(
      <DiagnosticsView
        diag={{
          turn_reachable: true,
          turn_host: 'turn.example.org',
          turn_port: 3478,
          vdo_process_up: true,
          coturn_process_up: false,
          ice_summary: 'vdo=running; coturn=external (documented); turn=reachable',
          detail: '',
        }}
      />,
    )
    expect(queryByText(/requires a compositor/)).toBeNull()
    expect(getByText(/No local coturn process, but TURN is reachable/i)).toBeTruthy()
    expect(getByText(/turn\.example\.org:3478/)).toBeTruthy()
  })

  it('still warns when coturn is down and TURN is unreachable', () => {
    const { getByText } = render(
      <DiagnosticsView
        diag={{ turn_reachable: false, vdo_process_up: true, coturn_process_up: false, ice_summary: '', detail: '' }}
      />,
    )
    expect(getByText(/requires a compositor/)).toBeTruthy()
  })

  it('wires the Test TURN connectivity button and shows a test error', () => {
    const onTest = vi.fn()
    const { getByRole, getByText } = render(
      <DiagnosticsView
        diag={{ turn_reachable: false, vdo_process_up: true, coturn_process_up: false }}
        onTestConnectivity={onTest}
        testing={false}
        testError={new Error('probe timed out')}
      />,
    )
    fireEvent.click(getByRole('button', { name: /Test TURN connectivity/i }))
    expect(onTest).toHaveBeenCalledOnce()
    expect(getByText(/probe timed out/i)).toBeTruthy()
  })

  it('disables the test button and shows a loading label while testing', () => {
    const { getByRole } = render(
      <DiagnosticsView
        diag={{ turn_reachable: false }}
        onTestConnectivity={vi.fn()}
        testing
      />,
    )
    // Accessible name comes from aria-label, not the visible "Testing…" text.
    const button = getByRole('button', { name: /Test TURN connectivity/i }) as HTMLButtonElement
    expect(button.textContent).toContain('Testing…')
    expect(button.disabled).toBe(true)
  })

  it('shows the coturn setup guidance from the install report', () => {
    const { getByText } = render(
      <DiagnosticsView
        diag={{ turn_reachable: false }}
        installReport={{
          vdo_installed: true,
          coturn_action:
            'coturn has no native Windows build. Configure an external TURN server...',
        }}
      />,
    )
    expect(getByText(/coturn has no native Windows build/i)).toBeTruthy()
  })
})

describe('InviteComposer + CreateRoomForm + RoomRow', () => {
  it('mints an invite with the chosen name', () => {
    const onMint = vi.fn()
    const { getByLabelText, getByText } = render(<InviteComposer onMint={onMint} pending={false} />)
    fireEvent.change(getByLabelText('Guest name'), { target: { value: 'Resident' } })
    fireEvent.click(getByText('Generate invite link'))
    expect(onMint).toHaveBeenCalledWith('Resident', 'council_member')
  })

  it('creates a room with name + channel', () => {
    const onCreate = vi.fn()
    const { getByLabelText, getByText } = render(<CreateRoomForm onCreate={onCreate} pending={false} />)
    fireEvent.change(getByLabelText('Room name'), { target: { value: 'Guests' } })
    fireEvent.change(getByLabelText('Channel id'), { target: { value: 'ch_gov' } })
    fireEvent.click(getByText('Create room'))
    expect(onCreate).toHaveBeenCalledWith({ channel_id: 'ch_gov', name: 'Guests' })
  })

  it('renders a room row with its state and selects on click', () => {
    const onSelect = vi.fn()
    const { getByText } = render(<RoomRow room={ROOM} selected={false} onSelect={onSelect} />)
    expect(getByText('Live')).toBeTruthy() // room state live -> "Live" (distinct from guest "On air")
    fireEvent.click(getByText('Chamber'))
    expect(onSelect).toHaveBeenCalled()
  })
})
