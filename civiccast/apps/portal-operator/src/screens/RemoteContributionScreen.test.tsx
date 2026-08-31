import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(cleanup)

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
  admitContributionGuest: vi.fn(),
  closeContributionRoom: vi.fn(),
  contributionDiagnostics: vi.fn(),
  createContributionRoom: vi.fn(),
  dropContributionGuest: vi.fn(),
  getContributionRoom: vi.fn(),
  getRemoteContributionInstallStatus: vi.fn(),
  getStaffIdentity: vi.fn(),
  listContributionRooms: vi.fn(),
  mintGuestInvite: vi.fn(),
  muteContributionGuest: vi.fn(),
  openContributionRoom: vi.fn(),
  putContributionGuestOnAir: vi.fn(),
  takeContributionGuestOffAir: vi.fn(),
  testTurnConnectivity: vi.fn(),
}))

import type { ContributionRoom, RemoteGuestSession, RoomDetail, StaffIdentityResponse } from '../types/api.generated'
import {
  closeContributionRoom,
  getContributionRoom,
  getStaffIdentity,
  listContributionRooms,
} from '../api/client'
import {
  CreateRoomForm,
  DiagnosticsView,
  GuestTray,
  InviteComposer,
  RemoteContributionScreen,
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

  describe('Drop requires confirmation (round-3 audit gap)', () => {
    it('does not drop the guest until the operator confirms, naming the guest', () => {
      const onAction = vi.fn()
      const { getByText, getByRole } = render(
        <GuestTray sessions={[guest()]} canOperate pending={false} onAction={onAction} />,
      )
      fireEvent.click(getByText('Drop'))

      const dialog = getByRole('alertdialog')
      expect(dialog.textContent).toContain('Drop Jane?')
      expect(onAction).not.toHaveBeenCalled()

      fireEvent.click(getByText('Drop guest'))
      expect(onAction).toHaveBeenCalledWith('gs_1', 'drop')
    })

    it('names the on-air/mid-broadcast consequence when the guest is currently on air', () => {
      const onAction = vi.fn()
      const onAir = guest({ admitted_at: '2026-01-01T00:01:00Z', state: 'on_air' })
      const { getByText, getByRole } = render(
        <GuestTray sessions={[onAir]} canOperate pending={false} onAction={onAction} />,
      )
      fireEvent.click(getByText('Drop'))
      const dialog = getByRole('alertdialog')
      expect(dialog.textContent).toContain('on air right now')
      expect(dialog.textContent).toMatch(/cuts from the broadcast/i)
    })

    it('drops nothing when the operator cancels', () => {
      const onAction = vi.fn()
      const { getByText, queryByRole } = render(
        <GuestTray sessions={[guest()]} canOperate pending={false} onAction={onAction} />,
      )
      fireEvent.click(getByText('Drop'))
      fireEvent.click(getByText('Cancel'))
      expect(queryByRole('alertdialog')).toBeNull()
      expect(onAction).not.toHaveBeenCalled()
    })
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

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <RemoteContributionScreen />
    </QueryClientProvider>,
  )
}

function roomDetail(overrides: Partial<RoomDetail> = {}): RoomDetail {
  return {
    room: ROOM,
    invites: [],
    sessions: [],
    ...overrides,
  }
}

describe('RemoteContributionScreen: Close room requires confirmation (round-3 audit gap)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'op_1', operator_display_name: 'Op', token_id: 'tok_1',
      scopes: [], roles: ['meeting_operator'],
    })
    vi.mocked(listContributionRooms).mockResolvedValue([ROOM])
    vi.mocked(getContributionRoom).mockResolvedValue(roomDetail())
  })

  it('does not close the room until the operator confirms, naming the room', async () => {
    const { findByText, findByRole, getByRole } = renderScreen()

    fireEvent.click(await findByText('Chamber'))
    fireEvent.click(await findByRole('button', { name: 'Close room' }))

    const dialog = await findByRole('alertdialog')
    expect(dialog.textContent).toContain('Close "Chamber"?')
    expect(dialog.textContent).toMatch(/disconnected immediately/i)
    expect(closeContributionRoom).not.toHaveBeenCalled()

    fireEvent.click(getByRole('button', { name: 'Close room now' }))
    await waitFor(() => expect(closeContributionRoom).toHaveBeenCalled())
    expect(vi.mocked(closeContributionRoom).mock.calls[0][0]).toBe('room_1')
  })

  it('closes nothing when the operator cancels', async () => {
    const { findByText, findByRole, getByRole, queryByRole } = renderScreen()

    fireEvent.click(await findByText('Chamber'))
    fireEvent.click(await findByRole('button', { name: 'Close room' }))
    await findByRole('alertdialog')

    fireEvent.click(getByRole('button', { name: 'Cancel' }))
    expect(queryByRole('alertdialog')).toBeNull()
    expect(closeContributionRoom).not.toHaveBeenCalled()
  })
})
