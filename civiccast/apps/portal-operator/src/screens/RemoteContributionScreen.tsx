// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S17 Remote Contribution operator console (build step 9 slice 3f).
// Brings remote humans onto a channel over the browser via self-hosted
// VDO.Ninja: create/open/close a contribution room (the director view embeds
// VDO.Ninja's own IFRAME UI), mint single-use guest invites to send out, and
// run a guest tray with a waiting-room admit gate + On-Air / Mute / Off-Air /
// Drop. The diagnostics drawer (support_admin) shows TURN reachability +
// VDO/coturn co-process health, and states honestly when the tier is not
// configured. No WebRTC client code lives here — the guest opens VDO.Ninja's
// own page; CivicCast only orchestrates rooms, invites, and sessions.

import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  admitContributionGuest,
  closeContributionRoom,
  contributionDiagnostics,
  createContributionRoom,
  dropContributionGuest,
  getContributionRoom,
  getStaffIdentity,
  listContributionRooms,
  mintGuestInvite,
  muteContributionGuest,
  openContributionRoom,
  putContributionGuestOnAir,
  takeContributionGuestOffAir,
} from '../api/client'
import type {
  ContributionRoom,
  GuestInvite,
  RemoteGuestSession,
  RoomOpened,
  VdoDiagnostics,
} from '../types/api.generated'
import {
  type Tone,
  connectionQualityLabel,
  connectionQualityTone,
  contributionRoleLabel,
  guestCanGoOnAir,
  guestStateLabel,
  guestStateTone,
  hasRole,
  roomStateLabel,
  roomStateTone,
} from './contribution-format'

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
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null)

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
      invalidate()
    },
  })
  const closeMutation = useMutation({
    mutationFn: closeContributionRoom,
    onSuccess: () => {
      setOpenResult(null)
      invalidate()
    },
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
        'on-air': putContributionGuestOnAir,
        mute: muteContributionGuest,
        'off-air': takeContributionGuestOffAir,
        drop: dropContributionGuest,
      }
      return fns[vars.action](vars.sessionId)
    },
    onSuccess: invalidate,
    onError: () => {},
  })

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
          Bring remote council members, presenters, and public comment onto the channel
          over the browser via self-hosted VDO.Ninja — no install for the guest.
        </p>
      </header>

      {tierUnavailable && (
        <div
          role="alert"
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: 'var(--cc-warn)', background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
        >
          Remote contribution isn’t configured yet. A compositor (the GStreamer wpesrc
          engine or OBS) plus self-hosted VDO.Ninja and coturn must be commissioned before
          guests can reach the channel. See the diagnostics drawer for status.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* --- Room panel --- */}
        <Card
          title="Rooms"
          aside={canCreate ? <Pill label="setup admin can create" tone="neutral" /> : undefined}
        >
          {canCreate && <CreateRoomForm onCreate={(p) => createMutation.mutate(p)} pending={createMutation.isPending} />}
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
            <p className="mt-3 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              No contribution rooms yet.
            </p>
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
                    onClick={() => closeMutation.mutate(detail.room.room_id)}
                    disabled={closeMutation.isPending}
                    className="rounded px-3 py-1 text-xs font-semibold"
                    style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
                  >
                    Close room
                  </button>
                </div>
              )}

              {openResult && detail?.room.state !== 'closed' && (
                <CopyableUrl label="Director view (embed in your switcher)" url={openResult.director_url} />
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
                pending={guestMutation.isPending}
                onAction={(sessionId, action) => guestMutation.mutate({ sessionId, action })}
              />
              {guestMutation.isError && (
                <p className="mt-1 text-xs" style={{ color: 'var(--cc-err)' }}>
                  {apiMessage(guestMutation.error, 'Action failed — please retry.')}
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
            <DiagnosticsView diag={diagnosticsQuery.data} />
          ) : (
            <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>Loading diagnostics…</p>
          )}
        </Card>
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
}: {
  onCreate: (p: { channel_id: string; name: string }) => void
  pending: boolean
}) {
  const [channelId, setChannelId] = useState('')
  const [name, setName] = useState('')
  const ready = channelId.trim() !== '' && name.trim() !== ''
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
      <input
        value={channelId}
        onChange={(e) => setChannelId(e.target.value)}
        placeholder="Channel id (e.g. gov-ch-1)"
        aria-label="Channel id"
        className="rounded border px-2 py-1 text-sm"
        style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      />
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
  pending,
  onAction,
}: {
  sessions: RemoteGuestSession[]
  canOperate: boolean
  pending: boolean
  onAction: (sessionId: string, action: string) => void
}) {
  const active = sessions.filter((s) => s.state !== 'ended' && s.state !== 'dropped')
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
              {canOperate && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {s.admitted_at === null && (
                    <GuestButton label="Admit" onClick={() => onAction(s.session_id, 'admit')} pending={pending} />
                  )}
                  <GuestButton
                    label="On air"
                    onClick={() => onAction(s.session_id, 'on-air')}
                    pending={pending}
                    disabled={!guestCanGoOnAir(s.state, s.admitted_at)}
                  />
                  {s.state === 'on_air' && (
                    <GuestButton label="Mute" onClick={() => onAction(s.session_id, 'mute')} pending={pending} />
                  )}
                  {s.state === 'on_air' && (
                    <GuestButton label="Off air" onClick={() => onAction(s.session_id, 'off-air')} pending={pending} />
                  )}
                  <GuestButton label="Drop" onClick={() => onAction(s.session_id, 'drop')} pending={pending} tone="warn" />
                </div>
              )}
            </li>
          ))}
        </ul>
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

export function DiagnosticsView({ diag }: { diag: VdoDiagnostics }) {
  const turnReachable = diag.turn_reachable ?? false
  const vdoUp = diag.vdo_process_up ?? false
  const coturnUp = diag.coturn_process_up ?? false
  const noCompositor = !vdoUp && !coturnUp
  return (
    <div className="flex flex-col gap-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
      <div className="flex flex-wrap gap-2">
        <Pill label={`TURN ${turnReachable ? 'reachable' : 'unreachable'}`} tone={turnReachable ? 'ok' : 'warn'} />
        <Pill label={`VDO ${vdoUp ? 'up' : 'down'}`} tone={vdoUp ? 'ok' : 'warn'} />
        <Pill label={`coturn ${coturnUp ? 'up' : 'down'}`} tone={coturnUp ? 'ok' : 'warn'} />
      </div>
      {diag.ice_summary && <p>ICE: {diag.ice_summary}</p>}
      {noCompositor && (
        <p role="status" style={{ color: 'var(--cc-warn)' }}>
          Remote contribution requires a compositor (the GStreamer engine or OBS) plus
          self-hosted VDO.Ninja and coturn — guests cannot reach the channel until they
          are commissioned. {diag.detail}
        </p>
      )}
    </div>
  )
}
