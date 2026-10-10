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
  beginTakeover: vi.fn(),
  closeContributionRoom: vi.fn(),
  contributionDiagnostics: vi.fn(),
  createContributionRoom: vi.fn(),
  dropContributionGuest: vi.fn(),
  getContributionRoom: vi.fn(),
  getRemoteContributionInstallStatus: vi.fn(),
  getStaffIdentity: vi.fn(),
  listEgressChannels: vi.fn(),
  listContributionRooms: vi.fn(),
  mintGuestInvite: vi.fn(),
  muteContributionGuest: vi.fn(),
  recordContributionMediaControlRequest: vi.fn(),
  openContributionRoom: vi.fn(),
  putContributionGuestOnAir: vi.fn(),
  takeContributionGuestOffAir: vi.fn(),
  testTurnConnectivity: vi.fn(),
}))

import type { ContributionRoom, RemoteGuestSession, RoomDetail, StaffEgressChannelSummary, StaffIdentityResponse } from '../types/api.generated'
import {
  beginTakeover,
  closeContributionRoom,
  getContributionRoom,
  getStaffIdentity,
  listEgressChannels,
  listContributionRooms,
  openContributionRoom,
  putContributionGuestOnAir,
  recordContributionMediaControlRequest,
  takeContributionGuestOffAir,
} from '../api/client'
import {
  CreateRoomForm,
  DiagnosticsView,
  GuestTray,
  InviteComposer,
  RemoteContributionScreen,
  RoomRow,
} from './RemoteContributionScreen'
import { sendVdoDirectorControl } from './remote-contribution-vdo'
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
  it('holds an un-admitted guest and disables provider controls until the director is loaded', () => {
    const onAdmit = vi.fn()
    const { getByText } = render(
      <GuestTray sessions={[guest()]} canOperate directorReady={false} pending={false} onAdmit={onAdmit} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={vi.fn()} onMarkLeft={vi.fn()} />,
    )
    expect(getByText('In waiting room')).toBeTruthy()
    expect(getByText('Admit')).toBeTruthy()
    expect((getByText('Mute guest camera') as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(getByText('Admit'))
    expect(onAdmit).toHaveBeenCalledWith('gs_1')
  })

  it('sends the supported targeted audio and camera commands without changing lifecycle status', () => {
    const onControl = vi.fn()
    const admitted = guest({ admitted_at: '2026-01-01T00:01:00Z' })
    const { getByText, queryByText } = render(
      <GuestTray sessions={[admitted]} canOperate directorReady pending={false} onAdmit={vi.fn()} onControl={onControl} onOffAir={vi.fn()} onDisconnect={vi.fn()} onMarkLeft={vi.fn()} />,
    )
    expect(queryByText('Admit')).toBeNull() // already admitted
    fireEvent.click(getByText('Mute guest camera'))
    expect(onControl).toHaveBeenCalledWith('gs_1', 'video_mute')
    fireEvent.click(getByText('Mute guest audio'))
    expect(onControl).toHaveBeenCalledWith('gs_1', 'audio_mute')
  })
})

describe('RemoteContributionScreen: Off air requests', () => {
  it('confirms Off air and sends both targeted requests to the same guest without changing lifecycle or channel state', async () => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'op_1', operator_display_name: 'Op', token_id: 'tok_1',
      scopes: [], roles: ['meeting_operator'],
    })
    vi.mocked(listContributionRooms).mockResolvedValue([ROOM])
    vi.mocked(getContributionRoom).mockResolvedValue(roomDetail({
      invites: [{
        invite_id: 'inv_1', room_id: 'room_1', guest_display_name: 'Jane',
        role: 'council_member', invite_token: 'invite-stream-1',
        expires_at: '2026-01-01T01:00:00Z', created_at: '2026-01-01T00:00:00Z',
      }],
      sessions: [guest({ state: 'on_air', admitted_at: '2026-01-01T00:01:00Z' })],
    }))
    vi.mocked(openContributionRoom).mockResolvedValue({ room: ROOM, director_url: 'https://vdo.example/room' })
    vi.mocked(recordContributionMediaControlRequest).mockResolvedValue(guest())

    const view = renderScreen()
    fireEvent.click(await view.findByText('Chamber'))
    fireEvent.click(await view.findByRole('button', { name: 'Open room' }))
    const iframe = await view.findByTitle('VDO.Ninja guest director') as HTMLIFrameElement
    fireEvent.load(iframe)
    const postMessage = vi.spyOn(iframe.contentWindow!, 'postMessage')

    expect(view.queryByRole('button', { name: 'Off air' })).toBeTruthy()
    fireEvent.click(view.getByRole('button', { name: 'Off air' }))
    const dialog = await view.findByRole('alertdialog')
    expect(dialog.textContent).toMatch(/mute Jane's audio and camera/i)
    expect(dialog.textContent).toMatch(/stays connected/i)
    expect(dialog.textContent).toMatch(/does not return the channel to its schedule/i)
    expect(postMessage).not.toHaveBeenCalled()
    expect(recordContributionMediaControlRequest).not.toHaveBeenCalled()

    fireEvent.click(view.getByRole('button', { name: 'Send off-air requests' }))

    await waitFor(() => expect(recordContributionMediaControlRequest).toHaveBeenCalledTimes(2))
    expect(postMessage.mock.calls).toEqual([
      [{ function: 'targetGuest', target: 'invite-stream-1', action: 'audio', value: false }, 'https://vdo.example'],
      [{ function: 'targetGuest', target: 'invite-stream-1', action: 'video', value: false }, 'https://vdo.example'],
    ])
    expect(recordContributionMediaControlRequest).toHaveBeenNthCalledWith(1, 'gs_1', 'audio_mute')
    expect(recordContributionMediaControlRequest).toHaveBeenNthCalledWith(2, 'gs_1', 'video_mute')
    expect(view.getByText('On air')).toBeTruthy()
    expect(putContributionGuestOnAir).not.toHaveBeenCalled()
    expect(takeContributionGuestOffAir).not.toHaveBeenCalled()
    expect(beginTakeover).not.toHaveBeenCalled()
    expect(view.getByRole('status').textContent).toMatch(/did not acknowledge either request/i)
    expect(view.getByRole('status').textContent).toMatch(/latest recorded request/i)
  })

  it('reports a partial Off air result when the second request cannot be recorded', async () => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'op_1', operator_display_name: 'Op', token_id: 'tok_1',
      scopes: [], roles: ['meeting_operator'],
    })
    vi.mocked(listContributionRooms).mockResolvedValue([ROOM])
    vi.mocked(getContributionRoom).mockResolvedValue(roomDetail({
      invites: [{
        invite_id: 'inv_1', room_id: 'room_1', guest_display_name: 'Jane',
        role: 'council_member', invite_token: 'invite-stream-1',
        expires_at: '2026-01-01T01:00:00Z', created_at: '2026-01-01T00:00:00Z',
      }],
      sessions: [guest()],
    }))
    vi.mocked(openContributionRoom).mockResolvedValue({ room: ROOM, director_url: 'https://vdo.example/room' })
    vi.mocked(recordContributionMediaControlRequest)
      .mockResolvedValueOnce(guest())
      .mockRejectedValueOnce(new Error('record unavailable'))

    const view = renderScreen()
    fireEvent.click(await view.findByText('Chamber'))
    fireEvent.click(await view.findByRole('button', { name: 'Open room' }))
    const iframe = await view.findByTitle('VDO.Ninja guest director') as HTMLIFrameElement
    fireEvent.load(iframe)

    expect(view.queryByRole('button', { name: 'Off air' })).toBeTruthy()
    fireEvent.click(view.getByRole('button', { name: 'Off air' }))
    fireEvent.click(view.getByRole('button', { name: 'Send off-air requests' }))

    const notice = await view.findByRole('status')
    expect(notice.textContent).toMatch(/partial/i)
    expect(notice.textContent).toMatch(/audio mute.*recorded as sent, not verified/i)
    expect(notice.textContent).toMatch(/camera mute request was sent.*could not be recorded/i)
    expect(notice.textContent).toMatch(/did not acknowledge either request/i)
    expect(notice.textContent).toMatch(/remains connected/i)
    expect(notice.textContent).toMatch(/does not return the channel to its schedule/i)
    expect(recordContributionMediaControlRequest).toHaveBeenNthCalledWith(1, 'gs_1', 'audio_mute')
    expect(recordContributionMediaControlRequest).toHaveBeenNthCalledWith(2, 'gs_1', 'video_mute')
    expect(view.getByText('In waiting room')).toBeTruthy()
    expect(takeContributionGuestOffAir).not.toHaveBeenCalled()
    expect(beginTakeover).not.toHaveBeenCalled()
  })
})

describe('GuestTray: remaining states and confirmation', () => {
  it('hides controls when the operator cannot operate', () => {
    const { queryByText, getByText } = render(
      <GuestTray sessions={[guest()]} canOperate={false} directorReady pending={false} onAdmit={vi.fn()} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={vi.fn()} onMarkLeft={vi.fn()} />,
    )
    expect(getByText('Jane')).toBeTruthy()
    expect(queryByText('Admit')).toBeNull()
    expect(queryByText('Disconnect guest')).toBeNull()
  })

  it('omits ended/dropped guests from the active tray', () => {
    const { getByText } = render(
      <GuestTray
        sessions={[guest({ session_id: 'gs_x', state: 'dropped' }), guest({ guest_display_name: 'Ann' })]}
        canOperate directorReady pending={false} onAdmit={vi.fn()} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={vi.fn()} onMarkLeft={vi.fn()}
      />,
    )
    expect(getByText('Guests (1)')).toBeTruthy()
    expect(getByText('Ann')).toBeTruthy()
  })

  describe('Disconnect requires confirmation', () => {
    it('does not send the hangup command until the operator confirms, naming the guest', () => {
      const onDisconnect = vi.fn()
      const { getByText, getByRole } = render(
        <GuestTray sessions={[guest()]} canOperate directorReady pending={false} onAdmit={vi.fn()} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={onDisconnect} onMarkLeft={vi.fn()} />,
      )
      fireEvent.click(getByText('Disconnect guest'))

      const dialog = getByRole('alertdialog')
      expect(dialog.textContent).toContain('Disconnect Jane?')
      expect(dialog.textContent).toContain('does not acknowledge completion')
      expect(onDisconnect).not.toHaveBeenCalled()

      fireEvent.click(getByText('Send disconnect request'))
      expect(onDisconnect).toHaveBeenCalledWith('gs_1')
    })

    it('cancels without sending a provider command', () => {
      const onDisconnect = vi.fn()
      const { getByText, getByRole } = render(
        <GuestTray sessions={[guest()]} canOperate directorReady pending={false} onAdmit={vi.fn()} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={onDisconnect} onMarkLeft={vi.fn()} />,
      )
      fireEvent.click(getByText('Disconnect guest'))
      fireEvent.click(getByText('Cancel'))
      expect(getByRole('heading', { name: 'Guests (1)' })).toBeTruthy()
      expect(onDisconnect).not.toHaveBeenCalled()
    })

    it('records a guest as left only after explicit confirmation that they were checked', () => {
      const onMarkLeft = vi.fn()
      const { getByText, getByRole } = render(
        <GuestTray sessions={[guest()]} canOperate directorReady pending={false} onAdmit={vi.fn()} onControl={vi.fn()} onOffAir={vi.fn()} onDisconnect={vi.fn()} onMarkLeft={onMarkLeft} />,
      )
      fireEvent.click(getByText('Mark left after checking'))
      expect(getByRole('alertdialog').textContent).toContain('after you verify in the director')
      expect(onMarkLeft).not.toHaveBeenCalled()
      fireEvent.click(getByText('Mark guest left'))
      expect(onMarkLeft).toHaveBeenCalledWith('gs_1')
    })
  })
})

describe('sendVdoDirectorControl', () => {
  it('uses the pinned director targetGuest shape and explicit mute values', () => {
    const postMessage = vi.fn()
    sendVdoDirectorControl({ postMessage }, 'https://vdo.example', 'invite-stream-1', 'video_mute')
    expect(postMessage).toHaveBeenCalledWith(
      { function: 'targetGuest', target: 'invite-stream-1', action: 'video', value: false },
      'https://vdo.example',
    )
  })

  it('sends a targeted hangup command for disconnect', () => {
    const postMessage = vi.fn()
    sendVdoDirectorControl({ postMessage }, 'https://vdo.example', 'invite-stream-1', 'disconnect')
    expect(postMessage).toHaveBeenCalledWith(
      { function: 'targetGuest', target: 'invite-stream-1', action: 'hangup' },
      'https://vdo.example',
    )
  })
})

describe('DiagnosticsView', () => {
  it('shows the guest-connectivity notice and warn pills when VDO and TURN are down', () => {
    const { getByText } = render(
      <DiagnosticsView diag={{ turn_reachable: false, vdo_process_up: false, coturn_process_up: false, ice_summary: '', detail: 'disabled' }} />,
    )
    expect(getByText('TURN unreachable')).toBeTruthy()
    expect(getByText(/Browser guest connectivity needs self-hosted VDO\.Ninja and a reachable TURN server/)).toBeTruthy()
  })

  it('shows healthy pills when everything is up', () => {
    const { getByText, queryByText } = render(
      <DiagnosticsView diag={{ turn_reachable: true, vdo_process_up: true, coturn_process_up: true, ice_summary: 'ok', detail: '' }} />,
    )
    expect(getByText('TURN reachable')).toBeTruthy()
    expect(queryByText(/Browser guest connectivity needs/)).toBeNull()
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
    expect(queryByText(/Browser guest connectivity needs/)).toBeNull()
    expect(getByText(/No local coturn process, but TURN is reachable/i)).toBeTruthy()
    expect(getByText(/turn\.example\.org:3478/)).toBeTruthy()
  })

  it('still warns when coturn is down and TURN is unreachable', () => {
    const { getByText } = render(
      <DiagnosticsView
        diag={{ turn_reachable: false, vdo_process_up: true, coturn_process_up: false, ice_summary: '', detail: '' }}
      />,
    )
    expect(getByText(/Browser guest connectivity needs/)).toBeTruthy()
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

  it('creates a room using an enabled configured channel', () => {
    const onCreate = vi.fn()
    const channels: StaffEgressChannelSummary[] = [
      { channel_id: 'ch_gov', enabled: true, sink_count: 1 },
      { channel_id: 'ch_disabled', enabled: false, sink_count: 1 },
    ]
    const { getByLabelText, getByText } = render(<CreateRoomForm onCreate={onCreate} pending={false} channels={channels} />)
    fireEvent.change(getByLabelText('Room name'), { target: { value: 'Guests' } })
    const channel = getByLabelText('Configured channel') as HTMLSelectElement
    expect(Array.from(channel.options).map((option) => option.value)).toEqual(['', 'ch_gov'])
    fireEvent.change(channel, { target: { value: 'ch_gov' } })
    fireEvent.click(getByText('Create room'))
    expect(onCreate).toHaveBeenCalledWith({ channel_id: 'ch_gov', name: 'Guests' })
  })

  it('prevents room creation when there are no enabled egress channels', () => {
    const onCreate = vi.fn()
    const { getByText, getByRole } = render(
      <CreateRoomForm onCreate={onCreate} pending={false} channels={[]} />,
    )
    expect(getByText(/No enabled egress channels/)).toBeTruthy()
    expect((getByRole('button', { name: 'Create room' }) as HTMLButtonElement).disabled).toBe(true)
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
    expect(dialog.textContent).toMatch(/director API does not acknowledge those requests/i)
    expect(dialog.textContent).toMatch(/does not return the channel to its schedule/i)
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

describe('RemoteContributionScreen: configured channels', () => {
  it('loads enabled egress channels for the setup-admin room form', async () => {
    vi.clearAllMocks()
    vi.mocked(getStaffIdentity).mockResolvedValue({
      operator_id: 'op_1', operator_display_name: 'Op', token_id: 'tok_1',
      scopes: [], roles: ['setup_admin'],
    })
    vi.mocked(listEgressChannels).mockResolvedValue([
      { channel_id: 'government', enabled: true, sink_count: 1 },
      { channel_id: 'disabled', enabled: false, sink_count: 1 },
    ])
    vi.mocked(listContributionRooms).mockResolvedValue([])

    const { findByLabelText, findByRole } = renderScreen()
    const channel = await findByLabelText('Configured channel') as HTMLSelectElement

    expect(vi.mocked(listEgressChannels)).toHaveBeenCalledOnce()
    await waitFor(() => {
      expect(Array.from(channel.options).map((option) => option.value)).toEqual(['', 'government'])
    })
    expect(await findByRole('button', { name: 'Create room' })).toBeTruthy()
  })
})
