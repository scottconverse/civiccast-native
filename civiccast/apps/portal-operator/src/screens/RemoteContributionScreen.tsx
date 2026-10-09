// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S17 Remote Contribution operator console (build step 9 slice 3f).
// Manages contribution rooms, guest invites and waiting-room admission, then
// sends supported targeted guest controls through the embedded VDO.Ninja
// director iframe. Control requests are recorded as unverified because the
// iframe has no completion callback; guest-to-channel composition remains a
// separate, unimplemented path. The diagnostics drawer (support_admin) shows
// TURN/VDO/coturn status and when the tier is not configured.

import { useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ConfirmDialog, type PendingConfirm } from '../components/ConfirmDialog'
import {
  ApiError,
  admitContributionGuest,
  beginTakeover,
  closeContributionRoom,
  contributionDiagnostics,
  createContributionRoom,
  dropContributionGuest,
  getContributionRoom,
  getRemoteContributionInstallStatus,
  getStaffIdentity,
  listEgressChannels,
  listContributionRooms,
  mintGuestInvite,
  openContributionRoom,
  recordContributionMediaControlRequest,
  testTurnConnectivity,
} from '../api/client'
import type {
  ContributionInstallReport,
  ContributionRoom,
  GuestInvite,
  RemoteGuestSession,
  RoomOpened,
  StaffEgressChannelSummary,
  VdoDiagnostics,
} from '../types/api.generated'
import type { ContributionMediaControlAction } from '../api/client'
import { sendVdoDirectorControl } from './remote-contribution-vdo'
import {
  type Tone,
  connectionQualityLabel,
  connectionQualityTone,
  contributionRoleLabel,
  guestStateLabel,
  guestStateTone,
  hasRole,
  roomStateLabel,
  roomStateTone,
} from './contribution-format'
import { EmptyState } from '../components/EmptyState'

const READ_ROLES = ['setup_admin', 'support_admin', 'meeting_operator']
const OPERATE_ROLES = ['meeting_operator']
const CREATE_ROLES = ['setup_admin']
const DIAG_ROLES = ['support_admin']

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function isUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  const d = (error.detail ?? '').toLowerCase()
  return error.status === 503 || d.includes('not configured') || d.includes('unavailable')
}

function Pill({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const palette = {
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)' },
    info: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-info)' },
  }[tone]
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {label}
    </span>
  )
}

function Card({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section
      className="rounded-xl border p-4"
      style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface-2)' }}
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--cc-ink)' }}>
          {title}
        </h3>
        {aside}
      </header>
      {children}
    </section>
  )
}

function CopyableUrl({ label, url }: { label: string; url: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(url)
    setCopied(true)
  }
  return (
    <div className="mt-2">
      <label className="text-[11px] font-medium" style={{ color: 'var(--cc-ink-2)' }}>
        {label}
      </label>
      <div className="mt-1 flex gap-2">
        <input
          readOnly
          value={url}
          aria-label={label}
          className="flex-1 rounded border px-2 py-1 text-xs"
          style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
        />
        <button
          type="button"
          onClick={copy}
          className="rounded px-2 py-1 text-xs font-semibold"
          style={{ background: 'var(--cc-accent-soft)', color: 'var(--cc-accent-ink)' }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  )
}

export function RemoteContributionScreen() {
  const qc = useQueryClient()
  const directorFrameRef = useRef<HTMLIFrameElement>(null)
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null)
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  const [mediaControlNotice, setMediaControlNotice] = useState<string | null>(null)
  const [directorReady, setDirectorReady] = useState(false)
  const [mediaControlPending, setMediaControlPending] = useState(false)

  const identityQuery = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity })
  const identity = identityQuery.data
  const canRead = hasRole(identity, READ_ROLES)
  const canOperate = hasRole(identity, OPERATE_ROLES)
  const canCreate = hasRole(identity, CREATE_ROLES)
  const canDiag = hasRole(identity, DIAG_ROLES)

  const roomsQuery = useQuery({
    queryKey: ['contribution-rooms'],
    queryFn: () => listContributionRooms(),
    enabled: canRead,
  })

  const egressChannelsQuery = useQuery({
    queryKey: ['egress-channels'],
    queryFn: listEgressChannels,
    enabled: canCreate,
  })

  const detailQuery = useQuery({
    queryKey: ['contribution-room', selectedRoomId],
    queryFn: () => getContributionRoom(selectedRoomId as string),
    enabled: canRead && selectedRoomId !== null,
    refetchInterval: 5000, // guest tray + room state are live signals
  })

  const diagnosticsQuery = useQuery({
    queryKey: ['contribution-diagnostics'],
    queryFn: contributionDiagnostics,
    enabled: canDiag,
    refetchInterval: 15000,
  })

  const installStatusQuery = useQuery({
    queryKey: ['contribution-install-status'],
    queryFn: getRemoteContributionInstallStatus,
    enabled: canDiag,
  })

  const turnTestMutation = useMutation({
    mutationFn: testTurnConnectivity,
    onSuccess: (diag) => {
      // The test result IS a fresher diagnostics snapshot -- show it
      // immediately instead of waiting for the next 15s poll.
      qc.setQueryData(['contribution-diagnostics'], diag)
    },
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['contribution-rooms'] })
    void qc.invalidateQueries({ queryKey: ['contribution-room', selectedRoomId] })
  }

  const [openResult, setOpenResult] = useState<RoomOpened | null>(null)
  const [mintedInvite, setMintedInvite] = useState<GuestInvite | null>(null)

  const createMutation = useMutation({
    mutationFn: createContributionRoom,
    onSuccess: (room) => {
      setSelectedRoomId(room.room_id)
      invalidate()
    },
  })
  const openMutation = useMutation({
    mutationFn: openContributionRoom,
    onSuccess: (result) => {
      setOpenResult(result)
      setDirectorReady(false)
      invalidate()
    },
  })
  const closeMutation = useMutation({
    mutationFn: async (roomId: string) => {
      const active = detail?.sessions.filter((session) => session.state !== 'ended' && session.state !== 'dropped') ?? []
      let disconnectRequestsSent = 0
      if (active.length > 0) {
        const director = directorFrameRef.current?.contentWindow
        if (!openResult?.director_url || !director || !directorReady) {
          throw new Error('Room remains open. Open the room director before closing so active guest disconnect requests can be sent.')
        }
        const targetOrigin = new URL(openResult.director_url).origin
        try {
          for (const session of active) {
            const invite = detail?.invites.find((item) => item.invite_id === session.invite_id)
            if (!invite?.invite_token) throw new Error(`Could not resolve the director stream for ${session.guest_display_name}.`)
            sendVdoDirectorControl(director, targetOrigin, invite.invite_token, 'disconnect')
            disconnectRequestsSent += 1
            await recordContributionMediaControlRequest(session.session_id, 'disconnect')
          }
        } catch (error) {
          const partial = disconnectRequestsSent > 0
            ? ` ${disconnectRequestsSent} request(s) may already have been sent; none were acknowledged.`
            : ''
          throw new Error(
            `Room remains open.${partial} ${apiMessage(error, 'Could not record a guest disconnect request.')}`,
            { cause: error },
          )
        }
      }
      return closeContributionRoom(roomId)
    },
    onSuccess: () => {
      setMediaControlNotice('Room record closed. Disconnect requests were sent where the director was open; VDO.Ninja did not acknowledge them. Verify guest media in the director and compositor.')
      invalidate()
    },
    onError: invalidate,
  })
  const mintMutation = useMutation({
    mutationFn: (vars: { roomId: string; name: string; role: string }) =>
      mintGuestInvite(vars.roomId, {
        guest_display_name: vars.name,
        role: vars.role as GuestInvite['role'],
      }),
    onSuccess: (invite) => {
      setMintedInvite(invite)
      invalidate()
    },
  })
  const guestMutation = useMutation({
    mutationFn: (vars: { sessionId: string; action: string }) => {
      const fns: Record<string, (id: string) => Promise<RemoteGuestSession>> = {
        admit: admitContributionGuest,
        drop: dropContributionGuest,
      }
      return fns[vars.action](vars.sessionId)
    },
    onSuccess: invalidate,
    onError: () => {},
  })
  const takeoverMutation = useMutation({
    mutationFn: (channelId: string) => beginTakeover(channelId, { reason: 'Operator selected live takeover from Remote Contribution.' }),
    onSuccess: () => setMediaControlNotice('Channel takeover started for its configured live source. This does not route a contribution guest into the channel.'),
  })

  const requestGuestControl = async (sessionId: string, action: ContributionMediaControlAction) => {
    setMediaControlPending(true)
    try {
      const director = directorFrameRef.current?.contentWindow
      if (!openResult?.director_url || !director || !directorReady) {
        throw new Error('Open the room director before sending a guest media control.')
      }
      const session = detail?.sessions.find((item) => item.session_id === sessionId)
      const invite = session && detail?.invites.find((item) => item.invite_id === session.invite_id)
      if (!invite?.invite_token) throw new Error('Could not resolve this guest’s VDO.Ninja stream id.')
      sendVdoDirectorControl(director, new URL(openResult.director_url).origin, invite.invite_token, action)
      try {
        await recordContributionMediaControlRequest(sessionId, action)
      } catch (error) {
        throw new Error(
          `The command was sent to VDO.Ninja, but CivicCast could not save its unverified request: ${apiMessage(error, 'save failed')}`,
          { cause: error },
        )
      }
      setMediaControlNotice(`${action.replaceAll('_', ' ')} command sent to the VDO.Ninja director; the provider did not acknowledge it. Check guest media in the director and compositor.`)
      invalidate()
    } finally {
      setMediaControlPending(false)
    }
  }

  if (identityQuery.isLoading) {
    return <p className="p-6 text-sm" style={{ color: 'var(--cc-ink-2)' }}>Loading…</p>
  }
  if (!canRead) {
    return (
      <div className="p-6">
        <h2 className="text-lg font-semibold" style={{ color: 'var(--cc-ink)' }}>
          Remote Contribution
        </h2>
        <p className="mt-2 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          You don’t have access to the remote-contribution console. It is available to
          meeting operators, setup admins, and support admins.
        </p>
      </div>
    )
  }

  const rooms = roomsQuery.data ?? []
  const detail = detailQuery.data ?? null
  const tierUnavailable = isUnavailable(openMutation.error) || isUnavailable(mintMutation.error)

  return (
    <div className="flex flex-col gap-4 p-6">
      <header>
        <h2 className="text-lg font-semibold" style={{ color: 'var(--cc-ink)' }}>
          Remote Contribution
        </h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Invite council members, presenters, and public commenters into a self-hosted
          VDO.Ninja room. Guest media composition into the broadcast channel requires a
          separate commissioned compositor path.
        </p>
      </header>

      {tierUnavailable && (
        <div
          role="alert"
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: 'var(--cc-warn)', background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
        >
          Remote guest connections aren’t configured yet. Self-hosted VDO.Ninja and a
          reachable TURN service are required for guests to join. Guest media composition
          into the broadcast channel is not integrated. See the diagnostics drawer for status.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* --- Room panel --- */}
        <Card
          title="Rooms"
          aside={canCreate ? <Pill label="setup admin can create" tone="neutral" /> : undefined}
        >
          {canCreate && (
            <CreateRoomForm
              onCreate={(p) => createMutation.mutate(p)}
              pending={createMutation.isPending}
              channels={egressChannelsQuery.data ?? []}
              channelsLoading={egressChannelsQuery.isLoading}
              channelsError={egressChannelsQuery.isError}
            />
          )}
          {createMutation.isError && (
            <p className="mt-2 text-xs" style={{ color: 'var(--cc-warn)' }}>
              {apiMessage(createMutation.error, 'Could not create the room.')}
            </p>
          )}
          {roomsQuery.isError ? (
            <p className="mt-3 text-xs" style={{ color: 'var(--cc-warn)' }}>
              {apiMessage(roomsQuery.error, 'Could not load rooms.')}
            </p>
          ) : rooms.length === 0 ? (
            <EmptyState
              headline="No contribution rooms yet."
              body="Contribution rooms manage browser guest invites and CivicCast session records. Create a room above; guest media composition into the broadcast channel requires a separate integration."
            />
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {rooms.map((room) => (
                <RoomRow
                  key={room.room_id}
                  room={room}
                  selected={room.room_id === selectedRoomId}
                  onSelect={() => {
                    setSelectedRoomId(room.room_id)
                    setOpenResult(null)
                    setDirectorReady(false)
                    setMintedInvite(null)
                  }}
                />
              ))}
            </ul>
          )}
        </Card>

        {/* --- Selected room: director + invites + guest tray --- */}
        <Card title={detail ? detail.room.name : 'Select a room'}>
          {!detail ? (
            <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              Choose a room to open it, send guest invites, and run the guest tray.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Pill label={roomStateLabel(detail.room.state)} tone={roomStateTone(detail.room.state)} />
                <span className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                  channel {detail.room.channel_id} · up to {detail.room.max_guests} guests
                </span>
              </div>
              <p className="text-xs" style={{ color: 'var(--cc-warn-text)' }}>
                Room and guest tags describe CivicCast records. They do not prove that media is in the broadcast.
              </p>

              {canOperate && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openMutation.mutate(detail.room.room_id)}
                    disabled={openMutation.isPending}
                    className="rounded px-3 py-1 text-xs font-semibold"
                    style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}
                  >
                    Open room
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setPendingConfirm({
                        title: `Take ${detail.room.channel_id} live?`,
                        body: 'This overrides the channel schedule and takes its configured live source. It does not route a contribution guest into the channel.',
                        confirmLabel: 'Take channel live',
                        run: () => takeoverMutation.mutate(detail.room.channel_id),
                      })
                    }
                    disabled={takeoverMutation.isPending}
                    className="rounded px-3 py-1 text-xs font-semibold"
                    style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
                  >
                    Take channel live
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setPendingConfirm({
                        title: `Close "${detail.room.name}"?`,
                        body: 'This records disconnect requests for active guests through the open VDO.Ninja director, then closes the CivicCast room record. The director API does not acknowledge those requests, so check the director and compositor to verify media ended. This does not return the channel to its schedule.',
                        confirmLabel: 'Close room now',
                        run: () => closeMutation.mutate(detail.room.room_id),
                      })
                    }
                    disabled={closeMutation.isPending}
                    className="rounded px-3 py-1 text-xs font-semibold"
                    style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
                  >
                    Close room
                  </button>
                </div>
              )}
              {closeMutation.isError && (
                <p role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
                  {apiMessage(closeMutation.error, 'Room close failed.')}
                </p>
              )}
              {takeoverMutation.isError && (
                <p role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
                  {apiMessage(takeoverMutation.error, 'Channel takeover failed.')}
                </p>
              )}

              {openResult && (
                <div className="flex flex-col gap-2">
                  <CopyableUrl label="VDO.Ninja director view" url={openResult.director_url} />
                  <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                    The director iframe can send supported guest controls. A sent command is not provider confirmation; this integration cannot verify guest mute state or compositor output.
                  </p>
                  <iframe
                    ref={directorFrameRef}
                    title="VDO.Ninja guest director"
                    src={openResult.director_url}
                    allow="autoplay; fullscreen; picture-in-picture"
                    onLoad={() => setDirectorReady(true)}
                    className="h-[560px] w-full rounded border"
                    style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)' }}
                  />
                </div>
              )}

              {canOperate && (
                <InviteComposer
                  pending={mintMutation.isPending}
                  onMint={(name, role) => mintMutation.mutate({ roomId: detail.room.room_id, name, role })}
                />
              )}
              {mintMutation.isError && (
                <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
                  {apiMessage(mintMutation.error, 'Could not mint the invite.')}
                </p>
              )}
              {mintedInvite?.view_url && (
                <CopyableUrl
                  label={`Guest link for ${mintedInvite.guest_display_name} — send this`}
                  url={mintedInvite.view_url}
                />
              )}
              <InviteList invites={detail.invites} />

              <GuestTray
                sessions={detail.sessions}
                canOperate={canOperate}
                directorReady={directorReady}
                pending={guestMutation.isPending || mediaControlPending}
                onAdmit={(sessionId) => guestMutation.mutate({ sessionId, action: 'admit' })}
                onControl={(sessionId, action) => {
                  void requestGuestControl(sessionId, action).catch((error: unknown) =>
                    setMediaControlNotice(apiMessage(error, 'The director control request could not be sent.')),
                  )
                }}
                onDisconnect={(sessionId) => {
                  void requestGuestControl(sessionId, 'disconnect')
                    .catch((error: unknown) =>
                      setMediaControlNotice(apiMessage(error, 'The guest disconnect request could not be completed.')),
                    )
                }}
                onMarkLeft={(sessionId) => guestMutation.mutate({ sessionId, action: 'drop' })}
              />
              {guestMutation.isError && (
                <p className="mt-1 text-xs" style={{ color: 'var(--cc-err)' }}>
                  {apiMessage(guestMutation.error, 'Action failed — please retry.')}
                </p>
              )}
              {mediaControlNotice && (
                <p role="status" className="text-xs" style={{ color: 'var(--cc-warn)' }}>
                  {mediaControlNotice}
                </p>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* --- Diagnostics drawer (support_admin) --- */}
      {canDiag && (
        <Card title="Diagnostics">
          {diagnosticsQuery.isError ? (
            <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
              {apiMessage(diagnosticsQuery.error, 'Could not load diagnostics.')}
            </p>
          ) : diagnosticsQuery.data ? (
            <DiagnosticsView
              diag={diagnosticsQuery.data}
              installReport={installStatusQuery.data}
              onTestConnectivity={() => turnTestMutation.mutate()}
              testing={turnTestMutation.isPending}
              testError={turnTestMutation.error}
            />
          ) : (
            <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>Loading diagnostics…</p>
          )}
        </Card>
      )}

      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          tone={pendingConfirm.tone}
          onConfirm={() => {
            pendingConfirm.run()
            setPendingConfirm(null)
          }}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}

export function RoomRow({
  room,
  selected,
  onSelect,
}: {
  room: ContributionRoom
  selected: boolean
  onSelect: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left"
        style={{
          borderColor: selected ? 'var(--cc-accent)' : 'var(--cc-line)',
          background: selected ? 'var(--cc-accent-soft)' : 'var(--cc-surface)',
        }}
      >
        <span className="text-sm font-medium" style={{ color: 'var(--cc-ink)' }}>{room.name}</span>
        <Pill label={roomStateLabel(room.state)} tone={roomStateTone(room.state)} />
      </button>
    </li>
  )
}

export function CreateRoomForm({
  onCreate,
  pending,
  channels,
  channelsLoading = false,
  channelsError = false,
}: {
  onCreate: (p: { channel_id: string; name: string }) => void
  pending: boolean
  channels: StaffEgressChannelSummary[]
  channelsLoading?: boolean
  channelsError?: boolean
}) {
  const [channelId, setChannelId] = useState('')
  const [name, setName] = useState('')
  const enabledChannels = channels.filter((channel) => channel.enabled)
  const selectedChannelIsEnabled = enabledChannels.some((channel) => channel.channel_id === channelId)
  const ready = selectedChannelIsEnabled && name.trim() !== ''
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) onCreate({ channel_id: channelId.trim(), name: name.trim() })
      }}
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Room name (e.g. Council Chamber Guests)"
        aria-label="Room name"
        className="rounded border px-2 py-1 text-sm"
        style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      />
      <select
        value={channelId}
        onChange={(e) => setChannelId(e.target.value)}
        aria-label="Configured channel"
        disabled={channelsLoading || channelsError || enabledChannels.length === 0}
        className="rounded border px-2 py-1 text-sm"
        style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      >
        <option value="">Select an enabled channel</option>
        {enabledChannels.map((channel) => (
          <option key={channel.channel_id} value={channel.channel_id}>{channel.channel_id}</option>
        ))}
      </select>
      {channelsLoading && <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>Loading configured channels…</p>}
      {channelsError && <p role="alert" className="text-xs" style={{ color: 'var(--cc-warn)' }}>Could not load configured channels. Reload this screen to try again.</p>}
      {!channelsLoading && !channelsError && enabledChannels.length === 0 && (
        <p className="text-xs" style={{ color: 'var(--cc-warn-text)' }}>No enabled egress channels are available. Enable a channel before creating a room.</p>
      )}
      <button
        type="submit"
        disabled={!ready || pending}
        className="self-start rounded px-3 py-1 text-xs font-semibold disabled:opacity-50"
        style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}
      >
        Create room
      </button>
    </form>
  )
}

export function InviteComposer({
  onMint,
  pending,
}: {
  onMint: (name: string, role: string) => void
  pending: boolean
}) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('council_member')
  const ready = name.trim() !== ''
  return (
    <form
      className="flex flex-col gap-2 rounded-lg border p-3"
      style={{ borderColor: 'var(--cc-line)' }}
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) {
          onMint(name.trim(), role)
          setName('')
        }
      }}
    >
      <span className="text-xs font-semibold" style={{ color: 'var(--cc-ink)' }}>Invite a guest</span>
      <p className="text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
        Generates a single-use browser link — no install required for the guest.
      </p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Guest name"
        aria-label="Guest name"
        className="rounded border px-2 py-1 text-sm"
        style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      />
      <select
        value={role}
        onChange={(e) => setRole(e.target.value)}
        aria-label="Contribution role"
        className="rounded border px-2 py-1 text-sm"
        style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      >
        <option value="council_member">{contributionRoleLabel('council_member')}</option>
        <option value="presenter">{contributionRoleLabel('presenter')}</option>
        <option value="public_comment">{contributionRoleLabel('public_comment')}</option>
      </select>
      <button
        type="submit"
        disabled={!ready || pending}
        className="self-start rounded px-3 py-1 text-xs font-semibold disabled:opacity-50"
        style={{ background: 'var(--cc-accent-soft)', color: 'var(--cc-accent-ink)' }}
      >
        Generate invite link
      </button>
    </form>
  )
}

export function InviteList({ invites }: { invites: GuestInvite[] }) {
  if (invites.length === 0) return null
  return (
    <div className="mt-2 flex flex-col gap-1">
      <h5 className="text-[11px] font-semibold" style={{ color: 'var(--cc-ink-2)' }}>
        Sent invites ({invites.length})
      </h5>
      {invites.map((inv) => (
        <div key={inv.invite_id} className="flex items-center justify-between text-[11px]">
          <span style={{ color: 'var(--cc-ink)' }}>
            {inv.guest_display_name} · {contributionRoleLabel(inv.role)}
          </span>
          <span style={{ color: inv.consumed_at ? 'var(--cc-ok)' : 'var(--cc-ink-2)' }}>
            {inv.consumed_at ? 'Used' : 'Pending'}
          </span>
        </div>
      ))}
    </div>
  )
}

export function GuestTray({
  sessions,
  canOperate,
  directorReady,
  pending,
  onAdmit,
  onControl,
  onDisconnect,
  onMarkLeft,
}: {
  sessions: RemoteGuestSession[]
  canOperate: boolean
  directorReady: boolean
  pending: boolean
  onAdmit: (sessionId: string) => void
  onControl: (sessionId: string, action: ContributionMediaControlAction) => void
  onDisconnect: (sessionId: string) => void
  onMarkLeft: (sessionId: string) => void
}) {
  const active = sessions.filter((s) => s.state !== 'ended' && s.state !== 'dropped')
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold" style={{ color: 'var(--cc-ink)' }}>
        Guests ({active.length})
      </h4>
      {active.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          No guests connected. Send an invite link to bring one in.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {active.map((s) => (
            <li
              key={s.session_id}
              className="rounded-lg border p-2"
              style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)' }}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium" style={{ color: 'var(--cc-ink)' }}>
                  {s.guest_display_name}
                </span>
                <span className="flex gap-1">
                  <Pill label={guestStateLabel(s.state)} tone={guestStateTone(s.state)} />
                  <Pill
                    label={connectionQualityLabel(s.connection_quality)}
                    tone={connectionQualityTone(s.connection_quality)}
                  />
                </span>
              </div>
              {(s as RemoteGuestSession & { media_control_state?: string; media_control_action?: string | null }).media_control_state === 'sent_unverified' && (
                <p className="mt-1 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
                  Last director command: {(s as RemoteGuestSession & { media_control_action?: string | null }).media_control_action?.replaceAll('_', ' ') ?? 'unknown'}; sent, not verified.
                </p>
              )}
              {canOperate && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {s.admitted_at === null && (
                    <GuestButton label="Admit" onClick={() => onAdmit(s.session_id)} pending={pending} />
                  )}
                  <GuestButton
                    label="Mute audio in director"
                    onClick={() => onControl(s.session_id, 'audio_mute')}
                    pending={pending}
                    disabled={!directorReady}
                  />
                  <GuestButton
                    label="Restore director audio"
                    onClick={() => onControl(s.session_id, 'audio_unmute')}
                    pending={pending}
                    disabled={!directorReady}
                  />
                  <GuestButton
                    label="Mute guest camera"
                    onClick={() => onControl(s.session_id, 'video_mute')}
                    pending={pending}
                    disabled={!directorReady}
                  />
                  <GuestButton
                    label="Restore guest camera"
                    onClick={() => onControl(s.session_id, 'video_unmute')}
                    pending={pending}
                    disabled={!directorReady}
                  />
                  <GuestButton
                    label="Disconnect guest"
                    onClick={() =>
                      setPendingConfirm({
                        title: `Disconnect ${s.guest_display_name}?`,
                        body: 'This sends VDO.Ninja’s targeted hangup command. The iframe does not acknowledge completion, so CivicCast keeps the session active until you verify the guest left.',
                        confirmLabel: 'Send disconnect request',
                        run: () => onDisconnect(s.session_id),
                      })
                    }
                    pending={pending}
                    tone="warn"
                    disabled={!directorReady}
                  />
                  <GuestButton
                    label="Mark left after checking"
                    onClick={() =>
                      setPendingConfirm({
                        title: `Record ${s.guest_display_name} as disconnected?`,
                        body: 'Use this only after you verify in the director that the guest is gone. It updates the CivicCast session record and does not send a provider command.',
                        confirmLabel: 'Mark guest left',
                        run: () => onMarkLeft(s.session_id),
                      })
                    }
                    pending={pending}
                    disabled={!directorReady}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {active.some((session) => session.state === 'on_air' || session.state === 'muted') && (
        <p className="mt-2 text-xs" style={{ color: 'var(--cc-warn-text)' }}>
          These lifecycle tags came from an earlier CivicCast workflow. They do not prove guest media routing or broadcast output.
        </p>
      )}

      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          tone={pendingConfirm.tone}
          onConfirm={() => {
            pendingConfirm.run()
            setPendingConfirm(null)
          }}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}

function GuestButton({
  label,
  onClick,
  pending,
  disabled = false,
  tone = 'neutral',
}: {
  label: string
  onClick: () => void
  pending: boolean
  disabled?: boolean
  tone?: 'neutral' | 'warn'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending || disabled}
      className="rounded px-2 py-0.5 text-[11px] font-semibold disabled:opacity-40"
      style={{
        background: tone === 'warn' ? 'var(--cc-warn-soft)' : 'var(--cc-surface-3)',
        color: tone === 'warn' ? 'var(--cc-warn)' : 'var(--cc-ink)',
      }}
    >
      {label}
    </button>
  )
}

export function DiagnosticsView({
  diag,
  installReport,
  onTestConnectivity,
  testing,
  testError,
}: {
  diag: VdoDiagnostics
  installReport?: ContributionInstallReport
  onTestConnectivity?: () => void
  testing?: boolean
  testError?: unknown
}) {
  const turnReachable = diag.turn_reachable ?? false
  const vdoUp = diag.vdo_process_up ?? false
  const coturnUp = diag.coturn_process_up ?? false
  // On the documented-external-TURN posture, a local coturn process is not
  // required; use TURN reachability as the guest-connectivity signal.
  const turnCommissioned = coturnUp || turnReachable
  const guestConnectivityUnavailable = !vdoUp || !turnCommissioned
  const externalTurnLikely = !coturnUp && turnReachable
  return (
    <div className="flex flex-col gap-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
      <div className="flex flex-wrap gap-2">
        <Pill label={`TURN ${turnReachable ? 'reachable' : 'unreachable'}`} tone={turnReachable ? 'ok' : 'warn'} />
        <Pill label={`VDO ${vdoUp ? 'up' : 'down'}`} tone={vdoUp ? 'ok' : 'warn'} />
        <Pill label={`coturn ${coturnUp ? 'up' : 'down'}`} tone={turnCommissioned ? 'ok' : 'warn'} />
      </div>
      {(diag.turn_host || diag.turn_port != null) && (
        <p className="cc-mono" style={{ color: 'var(--cc-ink-3)' }}>
          Configured TURN target: {diag.turn_host ?? '—'}:{diag.turn_port ?? '—'}
        </p>
      )}
      {externalTurnLikely && (
        <p style={{ color: 'var(--cc-ink-3)' }}>
          No local coturn process, but TURN is reachable — expected for a documented
          external TURN server (see below).
        </p>
      )}
      {diag.ice_summary && <p>ICE: {diag.ice_summary}</p>}
      {guestConnectivityUnavailable && (
        <p role="status" style={{ color: 'var(--cc-warn)' }}>
          Browser guest connectivity needs self-hosted VDO.Ninja and a reachable TURN
          server (local coturn, or a documented external one). This status checks those
          services; it does not verify guest media composition into a channel. {diag.detail}
        </p>
      )}
      {onTestConnectivity && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            aria-label="Test TURN connectivity"
            disabled={testing}
            onClick={onTestConnectivity}
            className="w-fit rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {testing ? 'Testing…' : 'Test TURN connectivity'}
          </button>
          <span style={{ color: 'var(--cc-ink-3)' }}>
            Probes {diag.turn_host ?? 'the configured TURN host'} right now, rather than
            waiting for the next automatic check.
          </span>
        </div>
      )}
      {Boolean(testError) && (
        <p role="alert" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(testError, 'TURN connectivity test failed.')}
        </p>
      )}
      {installReport?.coturn_action && (
        <details>
          <summary className="cursor-pointer font-semibold" style={{ color: 'var(--cc-ink)' }}>
            How to point this station at coturn
          </summary>
          <p className="mt-1 whitespace-pre-wrap">{installReport.coturn_action}</p>
        </details>
      )}
    </div>
  )
}
