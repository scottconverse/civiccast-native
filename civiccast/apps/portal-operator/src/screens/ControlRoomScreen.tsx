// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S16 Production & Control Room operator console (build step 9 slice 2e).
// Drives the station's existing switchers (OBS/vMix/ATEM/…) through the TSR
// sidecar: a device strip, a surface's cue banks as tap targets with a
// plan-before-fire preview + two-step confirm, a program-feed banner that makes
// the S16->S5 boundary visible, and an append-only fired-cue audit drawer. The
// console degrades honestly when the TSR control service is unavailable.

import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  closeControlRoomSession,
  createSupportBundle,
  fireControlRoomCue,
  getControlRoomReadiness,
  getControlRoomSessionAudit,
  getControlSurface,
  getStaffIdentity,
  listControlSurfaces,
  listProductionDevices,
  openControlRoomSession,
  planControlRoomCue,
  probeProductionDevice,
  rollbackControlRoomSession,
} from '../api/client'
import type {
  ControlRoomSession,
  CueFiredEvent,
  CuePlan,
  DiagnosticBundleResponse,
  ProductionDevice,
  StaffIdentityResponse,
  TimelineCue,
  TsrProbeResult,
} from '../types/api.generated'
import {
  cueActionLabel,
  cueResultLabel,
  deviceHealthLabel,
  deviceKindLabel,
  deviceReachability,
} from './control-room-format'
import { ControlRoomReadinessPanel } from './ControlRoomReadinessPanel'

const READ_ROLES = ['setup_admin', 'support_admin', 'meeting_operator']
type SessionMode = NonNullable<ControlRoomSession['mode']>

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function isUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  const d = (error.detail ?? '').toLowerCase()
  return error.status === 502 || error.status === 503 || d.includes('not configured') || d.includes('unavailable')
}

function Pill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'ok' | 'warn' | 'info' }) {
  const palette = {
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
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

function Banner({ tone, children }: { tone: 'err' | 'warn' | 'info' | 'ok'; children: ReactNode }) {
  const c = {
    err: { bg: 'var(--cc-err-soft)', bd: 'var(--cc-err)' },
    warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
    info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
    ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
  }[tone]
  const role = tone === 'err' || tone === 'warn' ? 'alert' : 'status'
  return (
    <div role={role} className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

// --- device strip ------------------------------------------------------------

export function DeviceStrip({
  devices,
  reach,
  canProbe,
  probingId,
  onProbe,
}: {
  devices: ProductionDevice[]
  reach: Record<string, boolean>
  canProbe: boolean
  probingId: string | null
  onProbe: (id: string) => void
}) {
  if (devices.length === 0) {
    return <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No production devices configured.</div>
  }
  return (
    <div className="flex flex-wrap gap-2">
      {devices.map((d) => {
        const r = deviceReachability(d.enabled ?? true, reach[d.device_id] ?? null)
        // Persisted health/state-freshness (S16 item 7): shown until this operator
        // probes again in this session, so a stale reading is visible up front.
        const health = deviceHealthLabel(d.last_reachable, d.last_probed_at)
        return (
          <div key={d.device_id} className="flex items-center gap-2 rounded-md px-3 py-2"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
            <span className="text-xs font-semibold">{d.label}</span>
            <span className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>{deviceKindLabel(d.kind)}</span>
            <Pill label={r.label} tone={r.tone} />
            {reach[d.device_id] === undefined && <Pill label={health.label} tone={health.tone} />}
            {canProbe && (
              <button type="button" onClick={() => onProbe(d.device_id)} disabled={probingId === d.device_id || !d.enabled}
                className="rounded px-2 py-0.5 text-[10px] font-semibold"
                style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {probingId === d.device_id ? 'Probing…' : 'Probe'}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

// --- cue plan preview --------------------------------------------------------

export function CuePlanPreview({ plan }: { plan: CuePlan }) {
  return (
    <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="font-semibold">{plan.label} — {cueActionLabel(plan.action)}</div>
      <div className="mt-1 font-mono" style={{ color: 'var(--cc-ink-2)' }}>{plan.command_preview}</div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <Pill label={plan.ready_to_send ? 'Ready to send' : 'Not ready'} tone={plan.ready_to_send ? 'ok' : 'warn'} />
        {plan.material_state_fingerprint && (
          <span style={{ color: 'var(--cc-ink-3)' }}>
            dry-run {plan.material_state_fingerprint.slice(0, 12)}
          </span>
        )}
        {((plan.take_delay_ms ?? 0) > 0 || (plan.post_roll_ms ?? 0) > 0) && (
          <span style={{ color: 'var(--cc-ink-3)' }}>
            take-delay {plan.take_delay_ms ?? 0}ms · post-roll {plan.post_roll_ms ?? 0}ms
          </span>
        )}
      </div>
      {plan.operator_action && (
        <div className="mt-1" style={{ color: plan.ready_to_send ? 'var(--cc-ink-3)' : 'var(--cc-warn)' }}>
          Next: {plan.operator_action}
        </div>
      )}
      <div className="mt-1 italic" style={{ color: 'var(--cc-ink-3)' }}>{plan.proof_boundary}</div>
    </div>
  )
}

// --- surface cue panel (plan -> confirm -> fire) -----------------------------

export function CueButton({
  cue,
  canFire,
  sessionMode,
  planned,
  busy,
  confirming,
  onPlan,
  onFire,
  onConfirmToggle,
}: {
  cue: TimelineCue
  canFire: boolean
  sessionMode: SessionMode | null
  planned: CuePlan | null
  busy: boolean
  confirming: boolean
  onPlan: () => void
  onFire: () => void
  onConfirmToggle: (on: boolean) => void
}) {
  const inTestMode = sessionMode !== 'on_air'
  const armLabel = inTestMode ? 'Test... (needs confirm)' : 'Fire... (needs confirm)'
  const actionLabel = inTestMode
    ? (cue.confirm_required ? 'Confirm test action' : 'Record test action')
    : (cue.confirm_required ? 'Confirm fire' : 'Fire cue')
  return (
    <div className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <button type="button" onClick={onPlan} disabled={busy}
        className="w-full rounded-md px-3 py-3 text-left text-sm font-semibold"
        style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}>
        {cue.label}
        <span className="ml-2 text-[10px] font-normal" style={{ color: 'var(--cc-ink-3)' }}>
          {cueActionLabel(cue.action)}{cue.confirm_required ? ' · confirm' : ''}
        </span>
      </button>
      {planned && planned.cue_id === cue.cue_id && (
        <div className="mt-2 space-y-2">
          <CuePlanPreview plan={planned} />
          {canFire && (
            cue.confirm_required && !confirming ? (
              <button type="button" onClick={() => onConfirmToggle(true)} disabled={!planned.ready_to_send}
                className="rounded-md px-3 py-1.5 text-xs font-semibold"
                style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
                {armLabel}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button type="button" onClick={onFire} disabled={busy || !planned.ready_to_send}
                  className="rounded-md px-3 py-1.5 text-xs font-semibold"
                  style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}>
                  {busy ? (inTestMode ? 'Recording...' : 'Firing...') : actionLabel}
                </button>
                {cue.confirm_required && confirming && (
                  <button type="button" onClick={() => onConfirmToggle(false)}
                    className="rounded-md px-3 py-1.5 text-xs"
                    style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                    Cancel
                  </button>
                )}
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}

// --- program-feed banner (the S16<->S5 boundary, read-only) ------------------

export function ProgramFeedBanner({ session }: { session: ControlRoomSession }) {
  return (
    <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-info-soft)', border: '1px solid var(--cc-info)' }}>
      <span className="font-semibold">Program feed: </span>
      {session.program_feed_source_ref ?? 'not bound to a live source yet'}
      <div className="mt-1" style={{ color: 'var(--cc-ink-2)' }}>
        This console produces the source. Taking it to air on a channel is a Playout (S5)
        action — it is not fired from here.
      </div>
    </div>
  )
}

export function SessionModeBanner({ session }: { session: ControlRoomSession }) {
  if (session.mode === 'on_air') {
    return (
      <Banner tone="warn">
        ON-AIR MODE - cue actions can be sent to production devices. Safe-state cue:
        {' '}{session.safe_state_cue_id ?? 'not configured'}.
      </Banner>
    )
  }
  return (
    <Banner tone="info">
      TEST MODE - device actions are blocked and recorded as test-only audit events.
    </Banner>
  )
}

export function SafeStatePanel({
  session,
  cues,
  planned,
  busy,
  planError,
  onPlan,
  onFire,
}: {
  session: ControlRoomSession
  cues: TimelineCue[]
  planned: CuePlan | null
  busy: boolean
  planError?: string | null
  onPlan: (cueId: string) => void
  onFire: (cueId: string) => void
}) {
  const safeCue = cues.find((cue) => cue.cue_id === session.safe_state_cue_id)
  const plannedSafe = safeCue && planned?.cue_id === safeCue.cue_id ? planned : null
  const isOnAir = session.mode === 'on_air'
  return (
    <div className="space-y-2 rounded-md p-3" style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">Safe State</div>
          <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            {safeCue
              ? `${safeCue.label} is the configured recovery cue for this session.`
              : 'No safe-state cue is configured for this session.'}
          </div>
        </div>
        {safeCue && <Pill label={cueActionLabel(safeCue.action)} tone="warn" />}
      </div>
      {safeCue && (
        <>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => onPlan(safeCue.cue_id)} disabled={busy}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
              Dry Run Safe State
            </button>
            <button type="button" onClick={() => onFire(safeCue.cue_id)}
              disabled={busy || !plannedSafe?.ready_to_send}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-warn)', color: 'var(--cc-warn-ink)' }}>
              {isOnAir ? 'Panic: Run Safe State' : 'Record Safe State Test'}
            </button>
          </div>
          {plannedSafe && <CuePlanPreview plan={plannedSafe} />}
          {planError && <Banner tone="err">{planError}</Banner>}
          {!plannedSafe && (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Dry Run checks the current device and cue state before this recovery cue can be sent.
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function ControlRoomSupportBundlePanel({ canCreate }: { canCreate: boolean }) {
  const [note, setNote] = useState('')
  const bundle = useMutation<DiagnosticBundleResponse, Error>({
    mutationFn: () => createSupportBundle({
      operator_note: note.trim() === ''
        ? 'Support bundle requested from Production Control Room.'
        : `Production Control Room note: ${note.trim()}`,
    }),
  })

  return (
    <section className="space-y-2 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div>
        <h2 className="text-sm font-semibold">Support bundle</h2>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Create a redacted troubleshooting bundle and review the contents before sharing it.
        </p>
      </div>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Operator note
        <textarea aria-label="Control-room support note" value={note} onChange={(e) => setNote(e.target.value)}
          disabled={!canCreate} rows={3}
          className="rounded-md px-2 py-1 text-sm"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
      </label>
      <button type="button" disabled={!canCreate || bundle.isPending} onClick={() => bundle.mutate()}
        className="rounded-md px-3 py-1.5 text-sm font-semibold"
        style={{ background: canCreate ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canCreate ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}>
        {bundle.isPending ? 'Creating bundle...' : 'Create support bundle'}
      </button>
      {!canCreate && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>Support bundles require support admin.</div>
      )}
      {bundle.error && <Banner tone="err">{apiMessage(bundle.error, 'Support bundle failed.')}</Banner>}
      {bundle.data && (
        <div role="status" aria-live="polite" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}>
          <div className="font-semibold">Support bundle ready</div>
          <div className="break-all font-mono">{bundle.data.path}</div>
          <div className="break-all font-mono">SHA-256 {bundle.data.sha256}</div>
          <div>{bundle.data.next_step}</div>
          {bundle.data.contains.length > 0 && (
            <div>
              Contains: <span className="font-mono">{bundle.data.contains.join(', ')}</span>
            </div>
          )}
          {bundle.data.excludes.length > 0 && (
            <div>
              Excludes: <span className="font-mono">{bundle.data.excludes.join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

// --- audit drawer ------------------------------------------------------------

export function SessionAuditDrawer({ events }: { events: CueFiredEvent[] }) {
  return (
    <div aria-live="polite" className="space-y-1">
      <div className="text-xs font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>Fired-cue audit</div>
      {events.length === 0 ? (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No cues fired this session.</div>
      ) : (
        events.map((e) => (
          <div key={e.event_id} className="flex items-center gap-2 text-xs">
            <Pill label={cueResultLabel(e.result)} tone={e.result === 'fired' ? 'ok' : e.result === 'failed' ? 'warn' : 'neutral'} />
            <span>{cueActionLabel(e.action)}</span>
            <span style={{ color: 'var(--cc-ink-3)' }}>{e.device_id}</span>
          </div>
        ))
      )}
    </div>
  )
}

// --- container ---------------------------------------------------------------

export function ControlRoomScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({ queryKey: ['staff-identity'], queryFn: getStaffIdentity })
  const roles = identityQuery.data?.roles ?? []
  const canRead = roles.some((r) => READ_ROLES.includes(r))
  const canOperate = roles.includes('meeting_operator')
  const canProbe = roles.includes('setup_admin') || roles.includes('support_admin')
  const canCreateSupportBundle = roles.includes('support_admin')

  const [surfaceId, setSurfaceId] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionMode, setSessionMode] = useState<SessionMode>('test')
  const [safeStateCueId, setSafeStateCueId] = useState<string>('')
  const [confirmOnAir, setConfirmOnAir] = useState(false)
  const [planned, setPlanned] = useState<CuePlan | null>(null)
  const [confirmingCueId, setConfirmingCueId] = useState<string | null>(null)
  const [reach, setReach] = useState<Record<string, boolean>>({})
  const [unavailable, setUnavailable] = useState(false)

  const devicesQuery = useQuery({ queryKey: ['cr-devices'], queryFn: listProductionDevices, enabled: canRead })
  const readinessQuery = useQuery({ queryKey: ['cr-readiness'], queryFn: getControlRoomReadiness, enabled: canRead })
  const surfacesQuery = useQuery({ queryKey: ['cr-surfaces'], queryFn: listControlSurfaces, enabled: canRead })
  const surfaceQuery = useQuery({
    queryKey: ['cr-surface', surfaceId],
    queryFn: () => getControlSurface(surfaceId as string),
    enabled: canRead && surfaceId != null,
  })
  const auditQuery = useQuery({
    queryKey: ['cr-audit', sessionId],
    queryFn: () => getControlRoomSessionAudit(sessionId as string),
    enabled: sessionId != null,
  })

  const [activeSession, setActiveSession] = useState<ControlRoomSession | null>(null)
  const invReadiness = () => qc.invalidateQueries({ queryKey: ['cr-readiness'] })

  const probeMut = useMutation({
    mutationFn: (id: string): Promise<TsrProbeResult> => probeProductionDevice(id),
    onSuccess: (res, id) => setReach((m) => ({ ...m, [id]: res.reachable })),
    onError: (err, id) => { setReach((m) => ({ ...m, [id]: false })); if (isUnavailable(err)) setUnavailable(true) },
  })
  const openMut = useMutation({
    mutationFn: () => openControlRoomSession({
      surface_id: surfaceId as string,
      mode: sessionMode,
      safe_state_cue_id: sessionMode === 'on_air' ? safeStateCueId : null,
      confirm_on_air: sessionMode === 'on_air' ? confirmOnAir : false,
    }),
    onSuccess: (s) => { setSessionId(s.session_id); setActiveSession(s); setPlanned(null); invReadiness() },
  })
  const closeMut = useMutation({
    mutationFn: () => closeControlRoomSession(sessionId as string),
    onSuccess: () => { setSessionId(null); setActiveSession(null); setPlanned(null); invReadiness() },
  })
  const planMut = useMutation({
    mutationFn: (cueId: string) => planControlRoomCue(sessionId as string, cueId),
    onMutate: () => setPlanned(null),
    onSuccess: (p) => { setPlanned(p); setUnavailable(false) },
    onError: (err) => { setPlanned(null); if (isUnavailable(err)) setUnavailable(true) },
  })
  const fireMut = useMutation({
    mutationFn: (cueId: string) => fireControlRoomCue(
      sessionId as string,
      cueId,
      planned?.cue_id === cueId && planned.material_state_fingerprint
        ? { material_state_fingerprint: planned.material_state_fingerprint }
        : null,
    ),
    onSuccess: () => {
      setConfirmingCueId(null)
      setPlanned(null)
      qc.invalidateQueries({ queryKey: ['cr-audit', sessionId] })
      invReadiness()
    },
    onError: (err) => {
      // A failed fire still leaves the two-step confirm UI armed (pre-existing
      // gap): clear it so the operator sees the error/rollback options instead
      // of a stuck "Confirm fire / Cancel" pair for a cue that already failed.
      setConfirmingCueId(null)
      if (isUnavailable(err)) setUnavailable(true)
      qc.invalidateQueries({ queryKey: ['cr-audit', sessionId] })
      invReadiness()
    },
  })
  const rollbackMut = useMutation({
    mutationFn: () => rollbackControlRoomSession(sessionId as string),
    onSuccess: () => {
      setPlanned(null)
      qc.invalidateQueries({ queryKey: ['cr-audit', sessionId] })
      invReadiness()
    },
    onError: (err) => {
      if (isUnavailable(err)) setUnavailable(true)
      qc.invalidateQueries({ queryKey: ['cr-audit', sessionId] })
    },
  })

  if (identityQuery.isLoading) {
    return <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
  }
  if (identityQuery.isError) {
    return <div className="px-6 py-10"><Banner tone="err">Could not load your staff identity. {apiMessage(identityQuery.error, '')}</Banner></div>
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          The Production Control Room requires the publish/meeting operator, setup admin, or
          support admin role. Ask your station admin for access.
        </Banner>
      </div>
    )
  }

  const cues: TimelineCue[] = surfaceQuery.data?.cues ?? []
  const safeStateCues = cues.filter((cue) => cue.confirm_required)
  const readinessReport = readinessQuery.data
  const readinessBlockers = readinessReport?.checks.filter((check) => check.status === 'blocked') ?? []
  const onAirReady = readinessReport?.ready_for_on_air === true
  const onAirReadinessBlocked = sessionMode === 'on_air' && !onAirReady
  const onAirOpenDisabled = openMut.isPending
    || (sessionMode === 'on_air' && (!safeStateCueId || !confirmOnAir || !onAirReady))
  const onAirBlockerSummary = readinessBlockers.length > 0
    ? `${readinessBlockers[0].label}: ${readinessBlockers[0].operator_action}`
    : 'Control-room readiness has not passed yet.'
  const onAirPrerequisites = [
    { label: 'Control-room readiness', done: onAirReady },
    { label: 'Safe-state cue selected', done: safeStateCueId.length > 0 },
    { label: 'On-Air responsibility acknowledged', done: confirmOnAir },
  ]

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Production Control Room</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Drive your OBS / vMix / ATEM / decks via the TSR control service. Cues are previewed
          before they fire.
        </p>
      </div>

      {unavailable && (
        <Banner tone="warn">
          Production control unavailable — the TSR control service is not running or not configured.
          Cues cannot fire until it is restored.
        </Banner>
      )}

      {readinessQuery.isLoading
        ? <Banner tone="info">Checking control-room readiness...</Banner>
        : readinessQuery.isError
        ? <Banner tone="warn">Could not load control-room readiness. {apiMessage(readinessQuery.error, '')}</Banner>
        : readinessQuery.data && <ControlRoomReadinessPanel report={readinessQuery.data} />}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Devices</h2>
        {devicesQuery.isError
          ? <Banner tone="err">Could not load devices. {apiMessage(devicesQuery.error, '')}</Banner>
          : <DeviceStrip devices={devicesQuery.data ?? []} reach={reach} canProbe={canProbe}
              probingId={probeMut.isPending ? probeMut.variables ?? null : null} onProbe={(id) => probeMut.mutate(id)} />}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Control surface</h2>
        {surfacesQuery.isError
          ? <Banner tone="err">Could not load surfaces. {apiMessage(surfacesQuery.error, '')}</Banner>
          : (
            <select aria-label="Control surface" value={surfaceId ?? ''}
              onChange={(e) => { setSurfaceId(e.target.value || null); setPlanned(null); setSafeStateCueId(''); setConfirmOnAir(false) }}
              className="rounded-md px-2 py-1 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
              <option value="">Select a surface…</option>
              {(surfacesQuery.data ?? []).map((s) => <option key={s.surface_id} value={s.surface_id}>{s.label}</option>)}
            </select>
          )}
      </section>

      {surfaceId && (
        <section className="space-y-2">
          {surfaceQuery.isLoading && <Banner tone="info">Loading cues for this surface...</Banner>}
          {surfaceQuery.isError && <Banner tone="err">Could not load this surface. {apiMessage(surfaceQuery.error, '')}</Banner>}
          {!surfaceQuery.isSuccess ? null : !canOperate ? (
            <Banner tone="info">Read-only — opening a session and firing cues requires the meeting operator role.</Banner>
          ) : !sessionId ? (
            <div className="space-y-2 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-xs font-semibold">
                  <input type="radio" name="control-room-session-mode" value="test"
                    checked={sessionMode === 'test'}
                    onChange={() => { setSessionMode('test'); setConfirmOnAir(false) }}
                    className="mr-1" />
                  Test Mode
                </label>
                <label className="text-xs font-semibold">
                  <input type="radio" name="control-room-session-mode" value="on_air"
                    checked={sessionMode === 'on_air'}
                    onChange={() => setSessionMode('on_air')}
                    className="mr-1" />
                  On-Air Mode
                </label>
              </div>
              {sessionMode === 'on_air' && (
                <div className="space-y-2">
                  {onAirReadinessBlocked && (
                    <Banner tone="warn">
                      On-Air Session is blocked until readiness passes. {onAirBlockerSummary}
                    </Banner>
                  )}
                  <ul id="on-air-prerequisites" aria-label="On-Air prerequisites" className="space-y-1 text-xs">
                    {onAirPrerequisites.map((item) => (
                      <li key={item.label} style={{ color: item.done ? 'var(--cc-ink-2)' : 'var(--cc-warn)' }}>
                        {item.done ? 'Ready' : 'Needs attention'}: {item.label}
                      </li>
                    ))}
                  </ul>
                  <div className="flex flex-wrap items-center gap-3">
                    <select aria-label="Safe-state cue" value={safeStateCueId}
                      onChange={(e) => setSafeStateCueId(e.target.value)}
                      className="rounded-md px-2 py-1 text-xs"
                      style={{ background: 'var(--cc-surface-3)', border: '1px solid var(--cc-line)' }}>
                      <option value="">Select safe-state cue...</option>
                      {safeStateCues.map((cue) => <option key={cue.cue_id} value={cue.cue_id}>{cue.label}</option>)}
                    </select>
                    <label className="text-xs font-semibold">
                      <input type="checkbox" checked={confirmOnAir}
                        onChange={(e) => setConfirmOnAir(e.target.checked)}
                        className="mr-1" />
                      I understand On-Air cue actions may be sent to production devices
                    </label>
                  </div>
                </div>
              )}
              <button type="button" onClick={() => openMut.mutate()}
                disabled={onAirOpenDisabled}
                aria-describedby={sessionMode === 'on_air' ? 'on-air-prerequisites' : undefined}
                className="rounded-md px-3 py-1.5 text-sm font-semibold"
                style={onAirOpenDisabled
                  ? { background: 'var(--cc-surface-3)', color: 'var(--cc-ink-3)' }
                  : { background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}>
                {openMut.isPending ? 'Opening...' : sessionMode === 'on_air' ? 'Open On-Air Session' : 'Open Test Session'}
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <Pill label={activeSession?.mode === 'on_air' ? 'On-Air session open' : 'Test session open'} tone={activeSession?.mode === 'on_air' ? 'warn' : 'info'} />
              <button type="button" onClick={() => closeMut.mutate()} disabled={closeMut.isPending}
                className="rounded-md px-3 py-1 text-xs font-semibold"
                style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {closeMut.isPending ? 'Ending...' : 'End session'}
              </button>
            </div>
          )}
          {openMut.isError && <Banner tone="err">{apiMessage(openMut.error, 'Could not open the session.')}</Banner>}

          {activeSession && (
            <div className="space-y-2">
              <SessionModeBanner session={activeSession} />
              <ProgramFeedBanner session={activeSession} />
              <SafeStatePanel session={activeSession} cues={cues} planned={planned}
                busy={planMut.isPending || fireMut.isPending}
                planError={planMut.isError && planMut.variables === activeSession.safe_state_cue_id
                  ? `Safe State dry run failed: ${apiMessage(planMut.error, 'Could not dry run the safe-state cue.')}`
                  : null}
                onPlan={(cueId) => planMut.mutate(cueId)}
                onFire={(cueId) => fireMut.mutate(cueId)} />
            </div>
          )}

          {surfaceQuery.isSuccess && (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {cues.map((cue) => (
                  <CueButton key={cue.cue_id} cue={cue} canFire={Boolean(sessionId) && canOperate}
                    sessionMode={activeSession?.mode ?? null}
                    planned={planned} busy={planMut.isPending || fireMut.isPending}
                    confirming={confirmingCueId === cue.cue_id}
                    onPlan={() => { if (sessionId) planMut.mutate(cue.cue_id) }}
                    onFire={() => fireMut.mutate(cue.cue_id)}
                    onConfirmToggle={(on) => setConfirmingCueId(on ? cue.cue_id : null)} />
                ))}
              </div>
              {cues.length === 0 && <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>This surface has no cues yet.</div>}
            </>
          )}
          {planMut.isError && !(activeSession?.safe_state_cue_id && planMut.variables === activeSession.safe_state_cue_id) && (
            <Banner tone={isUnavailable(planMut.error) ? 'warn' : 'err'}>{apiMessage(planMut.error, 'Could not dry run the cue.')}</Banner>
          )}
          {fireMut.isError && !unavailable && (
            <Banner tone="err">{apiMessage(fireMut.error, 'Could not fire the cue.')}</Banner>
          )}
          {fireMut.isError && activeSession?.mode === 'on_air' && activeSession.safe_state_cue_id && (
            <div className="flex justify-start">
              <button type="button" onClick={() => rollbackMut.mutate()} disabled={rollbackMut.isPending}
                className="rounded-md px-3 py-1.5 text-xs font-semibold"
                style={{ background: 'var(--cc-warn)', color: 'var(--cc-warn-ink)' }}>
                {rollbackMut.isPending ? 'Rolling back...' : 'Roll back to Safe State'}
              </button>
            </div>
          )}
          {rollbackMut.isError && (
            <Banner tone="err">{apiMessage(rollbackMut.error, 'Could not roll back to Safe State.')}</Banner>
          )}
          {rollbackMut.isSuccess && !rollbackMut.isPending && (
            <Banner tone="ok">Rolled back to Safe State.</Banner>
          )}
          {fireMut.isSuccess && !fireMut.isPending && (
            <Banner tone="ok">
              {fireMut.data?.result === 'planned' ? 'Test action recorded.' : 'Cue fired.'}
            </Banner>
          )}
        </section>
      )}

      {sessionId && (
        <section><SessionAuditDrawer events={auditQuery.data ?? []} /></section>
      )}
      <ControlRoomSupportBundlePanel canCreate={canCreateSupportBundle} />
    </div>
  )
}
