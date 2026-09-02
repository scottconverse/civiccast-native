import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ApiError,
  getFacilityRouterInventory,
  getFacilityRouterPanel,
  getStaffIdentity,
  listChannelProfiles,
  previewOverlayCompositorPlan,
  previewFacilityRouterSchedulePlan,
  previewFacilityRouterTake,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type {
  ChannelProfile,
  OverlayCompositorPlan,
  RouterEndpoint,
  RouterInput,
  RouterInventory,
  RouterOutput,
  RouterScheduledTakePlan,
  RouterTakePlan,
  VirtualRouterButton,
  VirtualRouterPanel,
} from '../types/api.generated'

const REQUESTED_BY = 'facility-operator'

// Every channel-dependent action (scheduled take, overlay, later L-bar) must
// name a currently configured channel the operator picked -- never an
// implicit first/default channel. Manual crosspoint preview below is
// facility-path scoped (endpoint/source/destination only) and does not take
// a channel_id, so it never reads this selection.
const CHOOSE_CHANNEL_FOR_TAKE = 'Choose a channel before scheduling a take.'
const CHOOSE_CHANNEL_FOR_OVERLAY = 'Choose a channel before previewing an overlay.'
const NO_CHANNELS_CONFIGURED =
  'No channels are configured yet. Configure a channel in Channel Ops before scheduling a take or previewing overlays.'
const CHANNELS_LOAD_ERROR = 'Configured channels could not load. Scheduled take and overlay actions are unavailable until they do.'
const CHANNEL_PERMISSION_MESSAGE =
  'Scheduling a take and previewing overlays require the meeting operator role.'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function StatusPill({
  label,
  tone = 'neutral',
}: {
  label: string
  tone?: 'neutral' | 'ok' | 'warn' | 'info'
}) {
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

function endpointTarget(endpoint: RouterEndpoint): string {
  if (endpoint.transport === 'rs232') {
    return `${endpoint.serial_port ?? 'serial port'} @ ${endpoint.baud_rate ?? 'baud'}`
  }
  return `${endpoint.host ?? 'host'}:${endpoint.port ?? 'port'}`
}

function inputsById(rows: RouterInput[]): Map<string, RouterInput> {
  return new Map(rows.map((row) => [row.input_id, row]))
}

function outputsById(rows: RouterOutput[]): Map<string, RouterOutput> {
  return new Map(rows.map((row) => [row.output_id, row]))
}

function ErrorPanel({ error }: { error: unknown }) {
  return (
    <div
      role="alert"
      className="rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
    >
      <div className="font-semibold">Facility router status could not load.</div>
      <div className="mt-1" style={{ color: 'var(--cc-ink-2)' }}>
        {apiMessage(error, 'Check the staff token and local API service.')}
      </div>
    </div>
  )
}

function EndpointPicker({
  endpoints,
  selectedId,
  onSelect,
}: {
  endpoints: RouterEndpoint[]
  selectedId: string
  onSelect: (endpointId: string) => void
}) {
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">Router endpoints</h2>
        <StatusPill label={`${endpoints.length} configured`} tone="info" />
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {endpoints.map((endpoint) => {
          const active = endpoint.endpoint_id === selectedId
          return (
            <button
              type="button"
              key={endpoint.endpoint_id}
              aria-pressed={active}
              onClick={() => onSelect(endpoint.endpoint_id)}
              className="grid min-h-28 gap-2 rounded-md p-3 text-left"
              style={{
                background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
                border: active ? '1px solid var(--cc-brand)' : '1px solid var(--cc-line)',
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="cc-truncate text-sm font-semibold">{endpoint.label}</div>
                  <div className="cc-mono mt-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                    {endpoint.vendor} / {endpoint.protocol}
                  </div>
                </div>
                <StatusPill label={endpoint.enabled === false ? 'off' : 'ready'} tone={endpoint.enabled === false ? 'warn' : 'ok'} />
              </div>
              <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
                {endpoint.transport.toUpperCase()} {endpointTarget(endpoint)}
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}

export function ChannelPicker({
  channels,
  selectedChannelId,
  isLoading,
  loadError,
  staleNotice,
  onSelect,
}: {
  channels: ChannelProfile[]
  selectedChannelId: string
  isLoading: boolean
  loadError: unknown
  staleNotice: string | null
  onSelect: (channelId: string) => void
}) {
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">Target channel</h2>
        <StatusPill
          label={selectedChannelId ? 'channel selected' : 'no channel selected'}
          tone={selectedChannelId ? 'ok' : 'warn'}
        />
      </div>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Scheduled takes, overlays, and later L-bar commands apply to this channel. Manual
        crosspoint preview below previews an endpoint path and does not require a channel.
      </p>
      {staleNotice != null && (
        <div
          role="alert"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
        >
          {staleNotice}
        </div>
      )}
      {loadError != null && (
        <div
          role="alert"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
        >
          {apiMessage(loadError, CHANNELS_LOAD_ERROR)}
        </div>
      )}
      {loadError == null && !isLoading && channels.length === 0 && (
        <div className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
          {NO_CHANNELS_CONFIGURED}
        </div>
      )}
      {channels.length > 0 && (
        <label className="grid gap-1 text-sm" htmlFor="facility-router-channel">
          <span className="sr-only">Target channel</span>
          <select
            id="facility-router-channel"
            value={selectedChannelId}
            onChange={(event) => onSelect(event.target.value)}
            className="w-full rounded-md px-3 py-2 text-sm outline-none"
            style={{
              background: 'var(--cc-surface-2)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          >
            <option value="">Choose a channel...</option>
            {channels.map((channel) => (
              <option key={channel.channel_id} value={channel.channel_id}>
                {channel.branding.display_name} ({channel.channel_id})
              </option>
            ))}
          </select>
        </label>
      )}
    </section>
  )
}

function MatrixSelect<T extends RouterInput | RouterOutput>({
  label,
  rows,
  getId,
  selectedId,
  onSelect,
}: {
  label: string
  rows: T[]
  getId: (row: T) => string
  selectedId: string
  onSelect: (id: string) => void
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-semibold">{label}</span>
      <select
        value={selectedId}
        onChange={(event) => onSelect(event.target.value)}
        className="rounded-md px-3 py-2 text-sm outline-none"
        style={{
          background: 'var(--cc-surface-2)',
          border: '1px solid var(--cc-line)',
          color: 'var(--cc-ink)',
        }}
      >
        {rows.map((row) => {
          const id = getId(row)
          return (
            <option key={id} value={id}>
              {row.label} ({row.physical_port})
            </option>
          )
        })}
      </select>
    </label>
  )
}

function VirtualButtonGrid({
  panel,
  sourceLabels,
  destinationLabels,
  selectedButtonId,
  onPreview,
}: {
  panel: VirtualRouterPanel | undefined
  sourceLabels: Map<string, RouterInput>
  destinationLabels: Map<string, RouterOutput>
  selectedButtonId: string | null
  onPreview: (button: VirtualRouterButton) => void
}) {
  if (!panel) {
    return (
      <section
        className="rounded-md p-4 text-sm"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        Loading virtual router panel.
      </section>
    )
  }
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">{panel.label}</h2>
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {panel.panel_id}
          </div>
        </div>
        <StatusPill label="preview only" tone="warn" />
      </div>
      <div
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${panel.mobile_columns ?? 2}, minmax(0, 1fr))` }}
      >
        {panel.buttons.map((button) => {
          const active = button.button_id === selectedButtonId
          const source = sourceLabels.get(button.source_id)
          const destination = destinationLabels.get(button.destination_id)
          return (
            <button
              type="button"
              key={button.button_id}
              disabled={!button.enabled}
              onClick={() => onPreview(button)}
              className="grid min-h-24 gap-1 rounded-md p-3 text-left text-sm"
              style={{
                background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
                border: active ? '1px solid var(--cc-brand)' : '1px solid var(--cc-line)',
                opacity: button.enabled ? 1 : 0.55,
              }}
            >
              <span className="font-semibold">{button.label}</span>
              <span className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                {source?.label ?? button.source_id} {'->'} {destination?.label ?? button.destination_id}
              </span>
              <span className="text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
                {button.operator_action}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}

function PlanPreview({ plan }: { plan: RouterTakePlan | null }) {
  if (!plan) {
    return (
      <section
        className="rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="m-0 text-sm font-semibold">Take preview</h2>
        <p className="m-0 mt-2 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Pick a virtual button or source/destination pair to preview the exact command before
          any facility hardware integration is enabled.
        </p>
      </section>
    )
  }
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">Take preview</h2>
          <div className="mt-0.5 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {plan.source_label} to {plan.destination_label}
          </div>
        </div>
        <StatusPill label={plan.ready_to_send ? 'ready' : 'blocked'} tone={plan.ready_to_send ? 'ok' : 'warn'} />
      </div>
      <dl className="grid gap-2 text-xs md:grid-cols-2">
        <div>
          <dt className="font-semibold">Target</dt>
          <dd className="m-0 cc-mono" style={{ color: 'var(--cc-ink-2)' }}>{plan.target}</dd>
        </div>
        <div>
          <dt className="font-semibold">Protocol</dt>
          <dd className="m-0 cc-mono" style={{ color: 'var(--cc-ink-2)' }}>{plan.protocol} / {plan.transport}</dd>
        </div>
      </dl>
      <div>
        <div className="text-xs font-semibold">Command</div>
        <pre
          className="m-0 mt-1 overflow-auto rounded-md p-3 text-[11px]"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          {plan.command_preview}
        </pre>
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Operator action.</strong> {plan.operator_action}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Proof boundary: {plan.proof_boundary}
      </div>
    </section>
  )
}

export function OverlayPlanPanel({
  plan,
  busy,
  error,
  disabledReason,
  onPreview,
}: {
  plan: OverlayCompositorPlan | null
  busy: boolean
  error: unknown
  disabledReason: string | null
  onPreview: () => void
}) {
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">Overlay compositor</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Preview L-bar and squeezeback output before starting the live compositor.
          </p>
        </div>
        <StatusPill label={plan?.gpu_accelerated ? plan.acceleration_mode : 'cpu plan'} tone={plan?.gpu_accelerated ? 'ok' : 'neutral'} />
      </div>
      {error != null && (
        <div
          role="alert"
          className="rounded-md p-3 text-sm"
          style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
        >
          {apiMessage(error, 'Overlay compositor preview failed.')}
        </div>
      )}
      <button
        type="button"
        onClick={onPreview}
        disabled={busy || disabledReason != null}
        className="rounded-md px-3 py-2 text-sm font-semibold"
        style={{
          background: busy || disabledReason != null ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
          color: busy || disabledReason != null ? 'var(--cc-ink-3)' : 'white',
          opacity: busy ? 0.65 : 1,
        }}
      >
        {busy ? 'Previewing overlay...' : 'Preview L-bar and squeezeback'}
      </button>
      {disabledReason != null && !busy && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {disabledReason}
        </div>
      )}
      {plan && (
        <div className="grid gap-2 text-xs">
          <div>
            <span className="font-semibold">Layer order: </span>
            {plan.ordered_layers.map((layer) => layer.kind).join(' -> ')}
          </div>
          <div>
            <span className="font-semibold">Encoder: </span>
            {plan.ffmpeg_args[plan.ffmpeg_args.indexOf('-c:v') + 1] ?? plan.acceleration_mode}
          </div>
          <pre
            className="m-0 overflow-auto rounded-md p-3 text-[11px]"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          >
            {plan.filter_complex}
          </pre>
          <div style={{ color: 'var(--cc-ink-3)' }}>Proof boundary: {plan.proof_boundary}</div>
        </div>
      )}
    </section>
  )
}

function ManualTakePanel({
  inventory,
  selectedEndpointId,
  selectedSourceId,
  selectedDestinationId,
  onSource,
  onDestination,
  onPreview,
  busy,
}: {
  inventory: RouterInventory
  selectedEndpointId: string
  selectedSourceId: string
  selectedDestinationId: string
  onSource: (id: string) => void
  onDestination: (id: string) => void
  onPreview: () => void
  busy: boolean
}) {
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">Manual crosspoint</h2>
        <StatusPill label={selectedEndpointId} tone="neutral" />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <MatrixSelect
          label="Source"
          rows={inventory.sources.filter((source) => source.enabled !== false)}
          getId={(source) => source.input_id}
          selectedId={selectedSourceId}
          onSelect={onSource}
        />
        <MatrixSelect
          label="Destination"
          rows={inventory.destinations.filter((destination) => destination.enabled !== false)}
          getId={(destination) => destination.output_id}
          selectedId={selectedDestinationId}
          onSelect={onDestination}
        />
      </div>
      <button
        type="button"
        onClick={onPreview}
        disabled={busy || !selectedSourceId || !selectedDestinationId}
        className="rounded-md px-3 py-2 text-sm font-semibold"
        style={{
          background: 'var(--cc-brand)',
          color: 'white',
          opacity: busy ? 0.65 : 1,
        }}
      >
        {busy ? 'Previewing...' : 'Preview take'}
      </button>
    </section>
  )
}

export function ScheduledTakePanel({
  plan,
  busy,
  error,
  disabledReason,
  onPreview,
}: {
  plan: RouterScheduledTakePlan | null
  busy: boolean
  error: unknown
  disabledReason: string | null
  onPreview: () => void
}) {
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">Scheduled router take</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Preview the automatic source take that arms before a scheduled program.
          </p>
        </div>
        <StatusPill label={plan?.automatic_take_ready ? 'ready' : 'preview'} tone={plan?.automatic_take_ready ? 'ok' : 'neutral'} />
      </div>
      {error != null && (
        <div
          role="alert"
          className="rounded-md p-3 text-sm"
          style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
        >
          {apiMessage(error, 'Scheduled router preview failed.')}
        </div>
      )}
      <button
        type="button"
        onClick={onPreview}
        disabled={busy || disabledReason != null}
        className="rounded-md px-3 py-2 text-sm font-semibold"
        style={{
          background: busy || disabledReason != null ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
          color: busy || disabledReason != null ? 'var(--cc-ink-3)' : 'white',
          opacity: busy ? 0.65 : 1,
        }}
      >
        {busy ? 'Previewing schedule...' : 'Preview scheduled take'}
      </button>
      {disabledReason != null && !busy && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {disabledReason}
        </div>
      )}
      {plan && (
        <div className="grid gap-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          <div>
            <span className="font-semibold">Armed take: </span>
            {new Date(plan.scheduled_take_at).toLocaleString()}
          </div>
          <div>
            <span className="font-semibold">Command: </span>
            <span className="cc-mono">{plan.take_plan.command_preview}</span>
          </div>
          <div style={{ color: 'var(--cc-ink-3)' }}>Proof boundary: {plan.proof_boundary}</div>
        </div>
      )}
    </section>
  )
}

export function FacilityRouterScreen() {
  const inventoryQuery = useQuery({
    queryKey: ['facility-router-inventory'],
    queryFn: getFacilityRouterInventory,
    refetchInterval: 30_000,
    retry: false,
  })
  const inventory = inventoryQuery.data
  const [selectedEndpointId, setSelectedEndpointId] = useState('')
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [selectedDestinationId, setSelectedDestinationId] = useState('')
  const [selectedButtonId, setSelectedButtonId] = useState<string | null>(null)
  const [latestPlan, setLatestPlan] = useState<RouterTakePlan | null>(null)
  const [latestOverlayPlan, setLatestOverlayPlan] = useState<OverlayCompositorPlan | null>(null)
  const [latestSchedulePlan, setLatestSchedulePlan] = useState<RouterScheduledTakePlan | null>(null)

  // Target channel for every channel-dependent action. Reuses the same
  // channel-profile API and query key Channel Ops and Live Room use, so the
  // list stays in one cache. Never defaults silently -- the operator must
  // pick, except when exactly one channel exists (auto-selected but still
  // shown, per WP-09).
  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    retry: false,
  })
  const channels = useMemo(() => channelsQuery.data ?? [], [channelsQuery.data])
  const [selectedChannelId, setSelectedChannelId] = useState('')
  const [staleChannelNotice, setStaleChannelNotice] = useState<string | null>(null)
  // Tracks the last `channels` reference this component reacted to, so the
  // render-time sync block below (React's "adjust state when a prop
  // changes" pattern -- https://react.dev/learn/you-might-not-need-an-effect)
  // runs exactly once per genuine channel-list change, not on every render.
  const [syncedChannels, setSyncedChannels] = useState(channels)

  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canOperateChannel =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'meeting_operator')

  function selectChannel(channelId: string) {
    setSelectedChannelId(channelId)
    setStaleChannelNotice(null)
    // Any preview built against the previous channel selection no longer
    // describes the newly selected (or cleared) channel -- clear it rather
    // than leave a stale plan on screen next to a different target.
    setLatestOverlayPlan(null)
    setLatestSchedulePlan(null)
  }

  if (channels !== syncedChannels) {
    setSyncedChannels(channels)
    if (channelsQuery.isSuccess) {
      if (selectedChannelId) {
        // If the previously selected channel disappears from the configured
        // list (deleted, disabled, renamed), clear the selection and any
        // preview data built against it instead of silently continuing to
        // target a channel that no longer exists.
        const stillConfigured = channels.some((channel) => channel.channel_id === selectedChannelId)
        if (!stillConfigured) {
          setStaleChannelNotice(
            `The previously selected channel (${selectedChannelId}) is no longer configured. Choose another channel.`,
          )
          setSelectedChannelId('')
          setLatestOverlayPlan(null)
          setLatestSchedulePlan(null)
        }
      } else if (channels.length === 1) {
        // Auto-select the single configured channel so the operator isn't
        // forced to click a one-item picker, but it still renders selected
        // (not silent) via the picker's own value.
        setSelectedChannelId(channels[0].channel_id)
      }
    }
  }

  function channelActionDisabledReason(kind: 'take' | 'overlay'): string | null {
    if (channelsQuery.isError) return CHANNELS_LOAD_ERROR
    if (channelsQuery.isSuccess && channels.length === 0) return NO_CHANNELS_CONFIGURED
    if (!selectedChannelId) return kind === 'take' ? CHOOSE_CHANNEL_FOR_TAKE : CHOOSE_CHANNEL_FOR_OVERLAY
    if (staffIdentityQuery.isSuccess && !canOperateChannel) return CHANNEL_PERMISSION_MESSAGE
    return null
  }

  const defaultEndpointId = useMemo(
    () => inventory?.endpoints.find((item) => item.enabled !== false)?.endpoint_id ?? inventory?.endpoints[0]?.endpoint_id ?? '',
    [inventory?.endpoints],
  )
  const defaultSourceId = useMemo(
    () => inventory?.sources.find((item) => item.enabled !== false)?.input_id ?? inventory?.sources[0]?.input_id ?? '',
    [inventory?.sources],
  )
  const defaultDestinationId = useMemo(
    () => inventory?.destinations.find((item) => item.enabled !== false)?.output_id ?? inventory?.destinations[0]?.output_id ?? '',
    [inventory?.destinations],
  )
  const activeEndpointId = selectedEndpointId || defaultEndpointId
  const activeSourceId = selectedSourceId || defaultSourceId
  const activeDestinationId = selectedDestinationId || defaultDestinationId

  const panelQuery = useQuery({
    queryKey: ['facility-router-panel', activeEndpointId],
    queryFn: () => getFacilityRouterPanel(activeEndpointId),
    enabled: activeEndpointId.length > 0,
    retry: false,
  })

  const previewMutation = useMutation({
    mutationFn: previewFacilityRouterTake,
    onSuccess: (plan) => setLatestPlan(plan),
  })
  const overlayMutation = useMutation({
    mutationFn: previewOverlayCompositorPlan,
    onSuccess: (plan) => setLatestOverlayPlan(plan),
  })
  const scheduleMutation = useMutation({
    mutationFn: previewFacilityRouterSchedulePlan,
    onSuccess: (plan) => setLatestSchedulePlan(plan),
  })

  const sourceLabels = useMemo(
    () => inputsById(inventory?.sources ?? []),
    [inventory?.sources],
  )
  const destinationLabels = useMemo(
    () => outputsById(inventory?.destinations ?? []),
    [inventory?.destinations],
  )

  function previewTake(sourceId: string, destinationId: string, buttonId: string | null) {
    if (!activeEndpointId || !sourceId || !destinationId) return
    setSelectedButtonId(buttonId)
    previewMutation.mutate({
      request_id: `portal-${Date.now()}`,
      endpoint_id: activeEndpointId,
      source_id: sourceId,
      destination_id: destinationId,
      requested_by: REQUESTED_BY,
      reason: buttonId ? `Virtual router button ${buttonId}` : 'Manual router preview',
    })
  }

  function previewOverlay() {
    if (!selectedChannelId) return
    overlayMutation.mutate({
      channel_id: selectedChannelId,
      input_url: `rtmp://127.0.0.1/live/${selectedChannelId}`,
      output_manifest_path: `live/${selectedChannelId}/overlay.m3u8`,
      acceleration_preference: 'auto',
      layers: [
        {
          layer_id: 'squeezeback-main',
          kind: 'squeezeback',
          label: 'Squeezeback main video',
          geometry: {
            x_percent: 4,
            y_percent: 4,
            width_percent: 68,
            height_percent: 72,
          },
        },
        {
          layer_id: 'lbar-message',
          kind: 'l-bar',
          label: 'L-bar message well',
          geometry: {
            x_percent: 0,
            y_percent: 76,
            width_percent: 100,
            height_percent: 24,
          },
          content_ref: 'cg://approved-bulletin-or-sponsor',
          opacity: 0.92,
        },
      ],
    })
  }

  function previewScheduledTake() {
    if (!activeEndpointId || !activeSourceId || !activeDestinationId || !selectedChannelId) return
    const startsAt = new Date(Date.now() + 15 * 60 * 1000).toISOString()
    scheduleMutation.mutate({
      request_id: `portal-schedule-${Date.now()}`,
      schedule_item_id: 'operator-preview-schedule',
      channel_id: selectedChannelId,
      starts_at: startsAt,
      endpoint_id: activeEndpointId,
      source_id: activeSourceId,
      destination_id: activeDestinationId,
      requested_by: REQUESTED_BY,
      preroll_seconds: 15,
      reason: 'Operator preview from facility router panel',
    })
  }

  if (inventoryQuery.isError) {
    return (
      <main className="grid gap-4 p-4 md:p-6">
        <ErrorPanel error={inventoryQuery.error} />
      </main>
    )
  }

  if (!inventory) {
    return (
      <main className="grid gap-4 p-4 md:p-6">
        <section
          className="rounded-md p-4 text-sm"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          Loading facility router inventory.
        </section>
      </main>
    )
  }

  return (
    <main className="grid gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold">Facility router</h1>
          <p className="m-0 mt-1 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Preview SDI/IP router takes from a phone, tablet, or control-room workstation before
            enabling hardware send.
          </p>
        </div>
        <StatusPill label="hardware send disabled" tone="warn" />
      </div>

      <ChannelPicker
        channels={channels}
        selectedChannelId={selectedChannelId}
        isLoading={channelsQuery.isLoading}
        loadError={channelsQuery.error}
        staleNotice={staleChannelNotice}
        onSelect={selectChannel}
      />

      {staffIdentityQuery.isSuccess && !canOperateChannel && (
        <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          {CHANNEL_PERMISSION_MESSAGE} Endpoint inventory and manual crosspoint preview remain
          available.
        </div>
      )}

      <EndpointPicker
        endpoints={inventory.endpoints}
        selectedId={activeEndpointId}
        onSelect={(endpointId) => {
          setSelectedEndpointId(endpointId)
          setSelectedButtonId(null)
          setLatestPlan(null)
        }}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <div className="grid gap-4">
          <VirtualButtonGrid
            panel={panelQuery.data}
            sourceLabels={sourceLabels}
            destinationLabels={destinationLabels}
            selectedButtonId={selectedButtonId}
            onPreview={(button) => {
              setSelectedSourceId(button.source_id)
              setSelectedDestinationId(button.destination_id)
              previewTake(button.source_id, button.destination_id, button.button_id)
            }}
          />
          <ManualTakePanel
            inventory={inventory}
            selectedEndpointId={activeEndpointId}
            selectedSourceId={activeSourceId}
            selectedDestinationId={activeDestinationId}
            onSource={(id) => {
              setSelectedSourceId(id)
              setSelectedButtonId(null)
            }}
            onDestination={(id) => {
              setSelectedDestinationId(id)
              setSelectedButtonId(null)
            }}
            onPreview={() => previewTake(activeSourceId, activeDestinationId, null)}
            busy={previewMutation.isPending}
          />
          <ScheduledTakePanel
            plan={latestSchedulePlan}
            busy={scheduleMutation.isPending}
            error={scheduleMutation.error}
            disabledReason={channelActionDisabledReason('take')}
            onPreview={previewScheduledTake}
          />
          <OverlayPlanPanel
            plan={latestOverlayPlan}
            busy={overlayMutation.isPending}
            error={overlayMutation.error}
            disabledReason={channelActionDisabledReason('overlay')}
            onPreview={previewOverlay}
          />
        </div>
        <div className="grid content-start gap-4">
          {previewMutation.isError && (
            <div
              role="alert"
              className="rounded-md p-3 text-sm"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              {apiMessage(previewMutation.error, 'Router take preview failed.')}
            </div>
          )}
          <PlanPreview plan={latestPlan} />
          <section
            className="rounded-md p-4 text-xs"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
          >
            Inventory generated {new Date(inventory.generated_at).toLocaleString()}. Proof boundary:
            {' '}{inventory.proof_boundary}
          </section>
        </div>
      </div>
    </main>
  )
}
