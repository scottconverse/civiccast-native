// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S16 Production Control Room — configuration & authoring console (build step 9
// slice 2f). The setup_admin surface that the operate console (ControlRoomScreen)
// consumes: register/edit devices (write-only secret), set the TSR profile +
// Take-Delay/Post-Roll transition timing (S18 gap-8), and author control surfaces
// and their timeline cues across ALL actions including the gap-8 facility
// actions (gpi_pulse / serial_send / router_take).

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createControlSurface,
  createProductionDevice,
  createTimelineCue,
  deleteProductionDevice,
  deleteTimelineCue,
  getControlRoomReadiness,
  getControlSurface,
  getStaffIdentity,
  listControlSurfaces,
  listProductionDevices,
  probeProductionDevice,
  upsertDeviceProfile,
} from '../api/client'
import type {
  ControlSurface,
  ProductionDevice,
  ProductionDeviceInput,
  StaffIdentityResponse,
  TimelineCueInput,
} from '../types/api.generated'
import {
  cueActionLabel,
  deviceHealthLabel,
  deviceKindLabel,
  deviceReachability,
} from './control-room-format'
import { ControlRoomReadinessPanel } from './ControlRoomReadinessPanel'

const DEVICE_KINDS = ['obs', 'vmix', 'atem', 'hyperdeck', 'ptz', 'osc', 'tcp', 'http', 'casparcg', 'gpi', 'serial']
const TRANSPORTS = ['tcp', 'udp', 'http', 'websocket', 'serial', 'gpi']
const CUE_ACTIONS = [
  'scene', 'input', 'transition', 'macro', 'deck_play', 'deck_cue', 'ptz_preset',
  'osc', 'http', 'overlay_push', 'overlay_clear', 'gpi_pulse', 'serial_send', 'router_take',
]
const CUE_PAYLOAD_TEMPLATES: Record<string, { label: string; description: string; payload: Record<string, unknown> }> = {
  scene: { label: 'Scene', description: 'Take a named OBS/vMix scene.', payload: { scene: 'CAM 1' } },
  input: { label: 'Input', description: 'Select an existing input without renaming it.', payload: { input: 'Camera 1' } },
  transition: { label: 'Transition', description: 'Run a transition with an optional duration.', payload: { transition: 'Fade', duration_ms: 500 } },
  macro: { label: 'Macro', description: 'Run a prebuilt switcher macro.', payload: { macro: 'OPEN_SHOW' } },
  deck_play: { label: 'Deck play', description: 'Play a clip or deck slot.', payload: { clip: 'opening_slate' } },
  deck_cue: { label: 'Deck cue', description: 'Cue a clip at a known position.', payload: { clip: 'opening_slate', timecode: '00:00:00:00' } },
  ptz_preset: { label: 'PTZ preset', description: 'Recall a VISCA/PTZ preset.', payload: { preset: 1 } },
  osc: { label: 'OSC', description: 'Send an OSC command.', payload: { path: '/civiccast/take', args: [] } },
  http: { label: 'HTTP', description: 'Call a local adapter endpoint.', payload: { method: 'POST', url: 'http://127.0.0.1:8088/api', body: {} } },
  overlay_push: { label: 'Overlay push', description: 'Push title/lower-third text.', payload: { layer: 1, title: 'Lower Third', text: 'Guest Name' } },
  overlay_clear: { label: 'Overlay clear', description: 'Clear an overlay layer.', payload: { layer: 1 } },
  gpi_pulse: { label: 'GPI pulse', description: 'Pulse a configured GPI pin.', payload: { pin: 'gpi-1', duration_ms: 250 } },
  serial_send: { label: 'Serial send', description: 'Send a serial command string.', payload: { port: 'COM1', message: 'TAKE\\r\\n' } },
  router_take: { label: 'Router take', description: 'Route a source to a destination.', payload: { source: '3', destination: '1' } },
}
type DeviceProbeState = { reachable: boolean | null; detail?: string }

function formatPayloadTemplate(action: string): string {
  return JSON.stringify(CUE_PAYLOAD_TEMPLATES[action]?.payload ?? {}, null, 2)
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function Banner({ tone, children }: { tone: 'err' | 'info'; children: React.ReactNode }) {
  const c = tone === 'err'
    ? { bg: 'var(--cc-err-soft)', bd: 'var(--cc-err)' }
    : { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' }
  const role = tone === 'err' ? 'alert' : 'status'
  return (
    <div role={role} className="rounded-md p-3 text-sm" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

const field = 'rounded-md px-2 py-1 text-sm'
const fieldStyle = { background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' } as const
const btn = 'rounded-md px-3 py-1.5 text-sm font-semibold'

// --- device form -------------------------------------------------------------

export function DeviceForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean
  onSubmit: (payload: ProductionDeviceInput) => void
}) {
  const [label, setLabel] = useState('')
  const [kind, setKind] = useState('obs')
  const [transport, setTransport] = useState('websocket')
  const [host, setHost] = useState('')
  const [port, setPort] = useState('')
  const [secret, setSecret] = useState('')
  const valid = label.trim().length > 0
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Device label
        <input aria-label="Device label" className={field} style={fieldStyle} value={label}
          onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Kind
        <select aria-label="Device kind" className={field} style={fieldStyle} value={kind}
          onChange={(e) => setKind(e.target.value)}>
          {DEVICE_KINDS.map((k) => <option key={k} value={k}>{deviceKindLabel(k)}</option>)}
        </select>
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Transport
        <select aria-label="Transport" className={field} style={fieldStyle} value={transport}
          onChange={(e) => setTransport(e.target.value)}>
          {TRANSPORTS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Host
        <input aria-label="Host" className={field} style={fieldStyle} value={host}
          onChange={(e) => setHost(e.target.value)} />
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Port
        <input aria-label="Port" type="number" className={field} style={fieldStyle} value={port}
          onChange={(e) => setPort(e.target.value)} />
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Secret (write-only)
        <input aria-label="Device secret" type="password" className={field} style={fieldStyle} value={secret}
          onChange={(e) => setSecret(e.target.value)} placeholder="kept in keyring" />
      </label>
      <button type="button" className={btn} disabled={!valid || submitting}
        style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}
        onClick={() => onSubmit({
          label: label.trim(),
          kind: kind as ProductionDeviceInput['kind'],
          transport: transport as ProductionDeviceInput['transport'],
          host: host.trim() || null, port: port ? Number(port) : null,
          enabled: true, notes: null, secret: secret || null,
        })}>
        {submitting ? 'Saving…' : 'Register device'}
      </button>
    </div>
  )
}

// --- profile form (timing) ---------------------------------------------------

export function DeviceProfileForm({
  device,
  submitting,
  onSubmit,
}: {
  device: ProductionDevice
  submitting: boolean
  onSubmit: (deviceId: string, payload: {
    tsr_device_type: string; options: Record<string, unknown>
    capability_map: Record<string, unknown>; take_delay_ms: number; post_roll_ms: number
  }) => void
}) {
  const [tsrType, setTsrType] = useState(device.kind.toUpperCase())
  const [takeDelay, setTakeDelay] = useState('0')
  const [postRoll, setPostRoll] = useState('0')
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        TSR device type
        <input aria-label={`${device.device_id} tsr type`} className={field} style={fieldStyle} value={tsrType}
          onChange={(e) => setTsrType(e.target.value)} />
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Take-delay (ms)
        <input aria-label={`${device.device_id} take delay`} type="number" className={field} style={fieldStyle}
          value={takeDelay} onChange={(e) => setTakeDelay(e.target.value)} />
      </label>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Post-roll (ms)
        <input aria-label={`${device.device_id} post roll`} type="number" className={field} style={fieldStyle}
          value={postRoll} onChange={(e) => setPostRoll(e.target.value)} />
      </label>
      <button type="button" className={btn} disabled={submitting}
        style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
        onClick={() => onSubmit(device.device_id, {
          tsr_device_type: tsrType.trim() || device.kind.toUpperCase(),
          options: {}, capability_map: {},
          take_delay_ms: Number(takeDelay) || 0, post_roll_ms: Number(postRoll) || 0,
        })}>
        {submitting ? 'Saving…' : 'Save profile'}
      </button>
    </div>
  )
}

// --- cue form ----------------------------------------------------------------

export function CueForm({
  devices,
  submitting,
  onSubmit,
}: {
  devices: ProductionDevice[]
  submitting: boolean
  onSubmit: (payload: TimelineCueInput) => void
}) {
  const [label, setLabel] = useState('')
  const [deviceId, setDeviceId] = useState(devices[0]?.device_id ?? '')
  const [action, setAction] = useState('scene')
  const [payloadText, setPayloadText] = useState(formatPayloadTemplate('scene'))
  const [confirm, setConfirm] = useState(false)
  const [bank, setBank] = useState('0')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const payloadErrorId = 'cue-payload-error'
  const selectedDeviceId = devices.some((device) => device.device_id === deviceId)
    ? deviceId
    : (devices[0]?.device_id ?? '')

  function submit() {
    let parsed: Record<string, unknown>
    try {
      parsed = payloadText.trim() ? JSON.parse(payloadText) : {}
    } catch {
      setJsonError('Payload must be valid JSON.')
      return
    }
    setJsonError(null)
    onSubmit({
      label: label.trim(), device_id: selectedDeviceId,
      action: action as TimelineCueInput['action'], payload: parsed,
      confirm_required: confirm, bank: Number(bank) || 0, position: 0,
    })
  }

  const valid = label.trim().length > 0 && selectedDeviceId.length > 0
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Cue label
          <input aria-label="Cue label" className={field} style={fieldStyle} value={label}
            onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Device
          <select aria-label="Cue device" className={field} style={fieldStyle} value={selectedDeviceId}
            onChange={(e) => setDeviceId(e.target.value)}>
            {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Action
          <select aria-label="Cue action" className={field} style={fieldStyle} value={action}
            onChange={(e) => {
              const next = e.target.value
              setAction(next)
              setPayloadText(formatPayloadTemplate(next))
            }}>
            {CUE_ACTIONS.map((a) => <option key={a} value={a}>{cueActionLabel(a)}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Bank
          <input aria-label="Cue bank" type="number" className={field} style={fieldStyle} value={bank}
            onChange={(e) => setBank(e.target.value)} />
        </label>
        <label className="flex items-center gap-1 text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          <input aria-label="Confirm required" type="checkbox" checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)} />
          Confirm
        </label>
      </div>
      <div className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-surface-3)', border: '1px solid var(--cc-line)' }}>
        <div className="font-semibold">{CUE_PAYLOAD_TEMPLATES[action]?.label ?? cueActionLabel(action)} payload</div>
        <div style={{ color: 'var(--cc-ink-3)' }}>{CUE_PAYLOAD_TEMPLATES[action]?.description ?? 'Edit the JSON payload for this action.'}</div>
        <button type="button" className="mt-2 rounded px-2 py-0.5 text-[10px] font-semibold"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
          onClick={() => setPayloadText(formatPayloadTemplate(action))}>
          Reset template
        </button>
      </div>
      <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        Payload (JSON)
        <textarea aria-label="Cue payload" className={`${field} font-mono`} style={fieldStyle} rows={5}
          aria-invalid={jsonError ? 'true' : 'false'}
          aria-describedby={jsonError ? payloadErrorId : undefined}
          value={payloadText} onChange={(e) => setPayloadText(e.target.value)} />
      </label>
      {jsonError && (
        <div id={payloadErrorId} role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
          {jsonError}
        </div>
      )}
      <button type="button" className={btn} disabled={!valid || submitting}
        style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }} onClick={submit}>
        {submitting ? 'Saving…' : 'Add cue'}
      </button>
    </div>
  )
}

// --- container ---------------------------------------------------------------

export function ControlRoomSetupScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({ queryKey: ['staff-identity'], queryFn: getStaffIdentity })
  const isSetupAdmin = (identityQuery.data?.roles ?? []).includes('setup_admin')

  const [surfaceId, setSurfaceId] = useState<string | null>(null)
  const [newSurfaceLabel, setNewSurfaceLabel] = useState('')
  const [deviceRemoveCandidate, setDeviceRemoveCandidate] = useState<string | null>(null)
  const [cueDeleteCandidate, setCueDeleteCandidate] = useState<string | null>(null)

  const devicesQuery = useQuery({ queryKey: ['cr-devices'], queryFn: listProductionDevices, enabled: isSetupAdmin })
  const readinessQuery = useQuery({ queryKey: ['cr-readiness'], queryFn: getControlRoomReadiness, enabled: isSetupAdmin })
  const surfacesQuery = useQuery({ queryKey: ['cr-surfaces'], queryFn: listControlSurfaces, enabled: isSetupAdmin })
  const surfaceQuery = useQuery({
    queryKey: ['cr-surface', surfaceId],
    queryFn: () => getControlSurface(surfaceId as string),
    enabled: isSetupAdmin && surfaceId != null,
  })

  const invReadiness = () => qc.invalidateQueries({ queryKey: ['cr-readiness'] })
  const invDevices = () => {
    qc.invalidateQueries({ queryKey: ['cr-devices'] })
    invReadiness()
  }
  const createDevice = useMutation({ mutationFn: createProductionDevice, onSuccess: invDevices })
  const removeDevice = useMutation({
    mutationFn: (id: string) => deleteProductionDevice(id),
    onSuccess: () => {
      setDeviceRemoveCandidate(null)
      invDevices()
    },
  })
  const [probeResults, setProbeResults] = useState<Record<string, DeviceProbeState>>({})
  const probeDevice = useMutation({
    mutationFn: (id: string) => probeProductionDevice(id),
    onSuccess: (res, id) => {
      setProbeResults((m) => ({ ...m, [id]: { reachable: res.reachable, detail: res.detail } }))
      // Refresh the persisted device-health/freshness badge only. Readiness is
      // intentionally NOT invalidated on a probe result (reachable or not) — a
      // single ad hoc "Test connection" click must not trigger an extra
      // readiness refetch/flicker for the operator; readiness catches up the
      // next time it's naturally fetched.
      qc.invalidateQueries({ queryKey: ['cr-devices'] })
    },
    onError: (err, id) => {
      setProbeResults((m) => ({
        ...m,
        [id]: { reachable: false, detail: apiMessage(err, 'Connection test failed.') },
      }))
      qc.invalidateQueries({ queryKey: ['cr-devices'] })
    },
  })
  const saveProfile = useMutation({
    mutationFn: ({ id, p }: { id: string; p: Parameters<typeof upsertDeviceProfile>[1] }) => upsertDeviceProfile(id, p),
    onSuccess: invReadiness,
  })
  const createSurface = useMutation({
    mutationFn: (label: string) => createControlSurface({ label, assigned_role: 'meeting_operator' }),
    onSuccess: () => {
      setNewSurfaceLabel('')
      qc.invalidateQueries({ queryKey: ['cr-surfaces'] })
      invReadiness()
    },
  })
  const addCue = useMutation({
    mutationFn: (p: Parameters<typeof createTimelineCue>[1]) => createTimelineCue(surfaceId as string, p),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cr-surface', surfaceId] })
      invReadiness()
    },
  })
  const removeCue = useMutation({
    mutationFn: (id: string) => deleteTimelineCue(id),
    onSuccess: () => {
      setCueDeleteCandidate(null)
      qc.invalidateQueries({ queryKey: ['cr-surface', surfaceId] })
      invReadiness()
    },
  })

  if (identityQuery.isLoading) return <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
  if (identityQuery.isError) return <div className="px-6 py-10"><Banner tone="err">Could not load your staff identity.</Banner></div>
  if (!isSetupAdmin) {
    return <div className="px-6 py-10"><Banner tone="info">Configuring the Production Control Room requires the setup admin role.</Banner></div>
  }

  const devices: ProductionDevice[] = devicesQuery.data ?? []
  const surfaces: ControlSurface[] = surfacesQuery.data ?? []

  return (
    <div className="space-y-5 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Control Room — setup</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Register the switchers you control, set their transition timing, and author cue surfaces.
        </p>
      </div>

      {readinessQuery.isLoading
        ? <Banner tone="info">Checking control-room readiness...</Banner>
        : readinessQuery.isError
        ? <Banner tone="err">Could not load control-room readiness. {apiMessage(readinessQuery.error, '')}</Banner>
        : readinessQuery.data && <ControlRoomReadinessPanel report={readinessQuery.data} />}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Devices</h2>
        <DeviceForm submitting={createDevice.isPending} onSubmit={(p) => createDevice.mutate(p)} />
        {createDevice.isError && <Banner tone="err">{apiMessage(createDevice.error, 'Could not register the device.')}</Banner>}
        {removeDevice.isError && <Banner tone="err">{apiMessage(removeDevice.error, 'Could not remove the device.')}</Banner>}
        {saveProfile.isError && <Banner tone="err">{apiMessage(saveProfile.error, 'Could not save the device profile.')}</Banner>}
        <div className="space-y-2">
          {devicesQuery.isLoading && <Banner tone="info">Loading production devices...</Banner>}
          {devicesQuery.isError && <Banner tone="err">Could not load production devices. {apiMessage(devicesQuery.error, '')}</Banner>}
          {devicesQuery.isSuccess && devices.map((d) => (
            <div key={d.device_id} className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">{d.label} <span className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>{deviceKindLabel(d.kind)}</span></span>
                  {(() => {
                    const probe = probeResults[d.device_id]
                    const reach = deviceReachability(d.enabled ?? true, probe?.reachable ?? null)
                    return (
                      <span role="status" aria-live="polite" className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                        style={{
                          background: reach.tone === 'ok' ? 'var(--cc-ok-soft)' : reach.tone === 'warn' ? 'var(--cc-warn-soft)' : 'var(--cc-surface-3)',
                          color: reach.tone === 'ok' ? 'var(--cc-ink)' : reach.tone === 'warn' ? 'var(--cc-ink)' : 'var(--cc-ink-2)',
                        }}>
                        {reach.label}
                      </span>
                    )
                  })()}
                  {(() => {
                    // Persisted device health / state freshness (S16 item 7) — survives a
                    // page reload, unlike the ephemeral "Test connection" result above.
                    const health = deviceHealthLabel(d.last_reachable, d.last_probed_at)
                    return (
                      <span title={d.last_probed_at ? `Last probed ${new Date(d.last_probed_at).toLocaleString()}` : 'Never probed'}
                        className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                        style={{
                          background: health.tone === 'ok' ? 'var(--cc-ok-soft)' : health.tone === 'warn' ? 'var(--cc-warn-soft)' : 'var(--cc-surface-3)',
                          color: health.tone === 'ok' ? 'var(--cc-ink)' : health.tone === 'warn' ? 'var(--cc-ink)' : 'var(--cc-ink-2)',
                        }}>
                        Health: {health.label}
                      </span>
                    )
                  })()}
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                    style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
                    onClick={() => probeDevice.mutate(d.device_id)}
                    disabled={probeDevice.isPending && probeDevice.variables === d.device_id}>
                    {probeDevice.isPending && probeDevice.variables === d.device_id ? 'Testing...' : 'Test connection'}
                  </button>
                  {deviceRemoveCandidate === d.device_id ? (
                    <>
                      <span role="status" className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                        Confirm remove {d.label}?
                      </span>
                      <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                        style={{ background: 'var(--cc-err)', color: 'var(--cc-err-ink)' }}
                        onClick={() => removeDevice.mutate(d.device_id)} disabled={removeDevice.isPending}>
                        Confirm remove
                      </button>
                      <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                        style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
                        onClick={() => setDeviceRemoveCandidate(null)} disabled={removeDevice.isPending}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                      style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
                      onClick={() => setDeviceRemoveCandidate(d.device_id)} disabled={removeDevice.isPending}>
                      Remove
                    </button>
                  )}
                </div>
              </div>
              {probeResults[d.device_id]?.detail && (
                <div role="status" aria-live="polite" className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>{probeResults[d.device_id].detail}</div>
              )}
              <div className="mt-2">
                <DeviceProfileForm device={d} submitting={saveProfile.isPending}
                  onSubmit={(id, p) => saveProfile.mutate({ id, p })} />
              </div>
            </div>
          ))}
          {devicesQuery.isSuccess && devices.length === 0 && <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No devices yet.</div>}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">Surfaces</h2>
        <div className="flex items-end gap-2">
          <label className="flex flex-col text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            New surface label
            <input aria-label="New surface label" className={field} style={fieldStyle} value={newSurfaceLabel}
              onChange={(e) => setNewSurfaceLabel(e.target.value)} />
          </label>
          <button type="button" className={btn} disabled={!newSurfaceLabel.trim() || createSurface.isPending}
            style={{ background: 'var(--cc-accent)', color: 'var(--cc-accent-ink)' }}
            onClick={() => createSurface.mutate(newSurfaceLabel.trim())}>
            {createSurface.isPending ? 'Saving…' : 'Create surface'}
          </button>
        </div>
        {createSurface.isError && <Banner tone="err">{apiMessage(createSurface.error, 'Could not create the surface.')}</Banner>}
        {surfacesQuery.isLoading && <Banner tone="info">Loading control surfaces...</Banner>}
        {surfacesQuery.isError && <Banner tone="err">Could not load control surfaces. {apiMessage(surfacesQuery.error, '')}</Banner>}
        <select aria-label="Edit surface" className={field} style={fieldStyle} value={surfaceId ?? ''}
          onChange={(e) => { setSurfaceId(e.target.value || null); setCueDeleteCandidate(null) }}
          disabled={surfacesQuery.isLoading || surfacesQuery.isError}>
          <option value="">Select a surface to author cues…</option>
          {surfaces.map((s) => <option key={s.surface_id} value={s.surface_id}>{s.label}</option>)}
        </select>
      </section>

      {surfaceId && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Cues</h2>
          {surfaceQuery.isLoading && <Banner tone="info">Loading cues for this surface...</Banner>}
          {surfaceQuery.isError && <Banner tone="err">Could not load this surface. {apiMessage(surfaceQuery.error, '')}</Banner>}
          {devices.length === 0 ? (
            <Banner tone="info">Register a production device before adding cues to this surface.</Banner>
          ) : (
            <CueForm devices={devices} submitting={addCue.isPending || surfaceQuery.isLoading || surfaceQuery.isError} onSubmit={(p) => addCue.mutate(p)} />
          )}
          {addCue.isError && <Banner tone="err">{apiMessage(addCue.error, 'Could not add the cue.')}</Banner>}
          {removeCue.isError && <Banner tone="err">{apiMessage(removeCue.error, 'Could not delete the cue.')}</Banner>}
          <div className="space-y-1">
            {surfaceQuery.isSuccess && (surfaceQuery.data?.cues ?? []).map((c) => (
              <div key={c.cue_id} className="flex items-center justify-between rounded-md px-3 py-2 text-sm"
                style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
                <span>{c.label} <span className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>{cueActionLabel(c.action)}</span></span>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {cueDeleteCandidate === c.cue_id ? (
                    <>
                      <span role="status" className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>Confirm delete?</span>
                      <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                        style={{ background: 'var(--cc-err)', color: 'var(--cc-err-ink)' }}
                        onClick={() => removeCue.mutate(c.cue_id)} disabled={removeCue.isPending}>Confirm delete</button>
                      <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                        style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
                        onClick={() => setCueDeleteCandidate(null)} disabled={removeCue.isPending}>Cancel</button>
                    </>
                  ) : (
                    <button type="button" className="rounded px-2 py-0.5 text-[10px] font-semibold"
                      style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
                      onClick={() => setCueDeleteCandidate(c.cue_id)} disabled={removeCue.isPending}>Delete</button>
                  )}
                </div>
              </div>
            ))}
            {surfaceQuery.isSuccess && (surfaceQuery.data?.cues ?? []).length === 0 && (
              <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>This surface has no cues yet.</div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
