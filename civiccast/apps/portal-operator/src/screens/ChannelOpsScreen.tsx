import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  applyHeadendProfile,
  runComplianceProbe,
  type EgressCommandAction,
  type EgressHealthSample,
  type EgressStateRow,
  getAppPlatformConfig,
  getChannelNowNext,
  getChannelPlayoutPlan,
  getChannelProofLog,
  getCtvFeed,
  getEgressConfig,
  getEgressHealth,
  getEgressState,
  listEgressChannels,
  getStaffIdentity,
  listChannelProfiles,
  listHeadendProfiles,
  queueEgressCommand,
  updateAppPlatformChannelBranding,
  updateAppPlatformConfig,
  updateEgressConfig,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { ConfirmDialog, type PendingConfirm } from '../components/ConfirmDialog'
import { feedCommandConfirmCopy } from './feed-command-confirm'
import { humanizeDuration } from '../format'
import { RadioCardGroup } from '../components/RadioCardGroup'
import { CableVerificationCard } from './CableVerificationCard'
import { LoudnessPlanCard } from './LoudnessPlanCard'
import { CaptionStatusCard } from './CaptionStatusCard'
import { AudioTracksCard } from './AudioTracksCard'
import { CommitToAirPanel } from './CommitToAirPanel'
import { TakeoverCard } from './TakeoverCard'
import type {
  ChannelBrandingUpdate,
  ChannelNowNext,
  ChannelPlayoutPlan,
  ChannelProfile,
  ChannelProofEvent,
  ChannelProofLog,
  ChannelPublicConfig,
  ComplianceProbeResult,
  CtvFeed,
  EgressConfig,
  HeadendProfile,
  PlayoutBlock,
  StationAppConfig,
  StationAppConfigUpdate,
} from '../types/api.generated'
import { stateLabel, toneForEgressState } from './status-language'

const POLL_MS = 30_000

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

type PlayoutStatus = NonNullable<PlayoutBlock['status']> | ChannelProofEvent['actual_status']
type ChannelOutput = NonNullable<ChannelProfile['outputs']>[number]
type AppChannelMap = Map<string, ChannelPublicConfig>

const fieldClass = 'rounded-md px-3 py-2 text-sm outline-none'
const fieldStyle = {
  background: 'var(--cc-surface-2)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

const EGRESS_TONE_STYLE: Readonly<Record<'ok' | 'warn' | 'err', { bg: string; fg: string }>> = {
  ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)' },
  err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)' },
}

function statusTone(status: PlayoutStatus) {
  if (status === 'playing' || status === 'completed') return { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)' }
  if (status === 'fallback' || status === 'failed') return { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)' }
  return { bg: 'var(--cc-info-soft)', fg: 'var(--cc-info)' }
}

function StatusPill({ label }: { label: PlayoutStatus }) {
  const tone = statusTone(label)
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {stateLabel(label)}
    </span>
  )
}

function ErrorPanel({ error }: { error: unknown }) {
  return (
    <div
      role="alert"
      className="rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)', color: 'var(--cc-ink)' }}
    >
      <div className="font-semibold">Channel status could not load.</div>
      <div className="mt-1">{apiMessage(error, 'Check the staff token and local API service.')}</div>
    </div>
  )
}

function ChannelCard({
  channel,
  appChannel,
  active,
  onSelect,
}: {
  channel: ChannelProfile
  appChannel: ChannelPublicConfig | undefined
  active: boolean
  onSelect: (channelId: string) => void
}) {
  const branding = appChannel?.branding ?? channel.branding
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onSelect(channel.channel_id)}
      className="grid min-h-36 gap-3 rounded-md p-4 text-left"
      style={{
        background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
        border: active ? '1px solid var(--cc-brand)' : '1px solid var(--cc-line)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-xs font-bold"
          style={{ background: branding.color, color: 'white' }}
        >
          {branding.logo_text}
        </div>
        <div className="min-w-0">
          <div className="text-base font-semibold">{branding.display_name}</div>
          <div className="cc-mono mt-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {channel.kind} / {channel.channel_id}
          </div>
        </div>
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {channel.fallback_behavior}
      </div>
    </button>
  )
}

function trimOptional(value: FormDataEntryValue | null): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function stationPatchFromForm(form: HTMLFormElement): StationAppConfigUpdate {
  const data = new FormData(form)
  return {
    station_name: trimOptional(data.get('station_name')),
    app_name: trimOptional(data.get('app_name')),
    default_channel_id: trimOptional(data.get('default_channel_id')),
    support_url: trimOptional(data.get('support_url')),
    privacy_url: trimOptional(data.get('privacy_url')),
    build_tier: data.get('build_tier') === 'branded' ? 'branded' : 'unbranded',
    analytics_enabled: data.get('analytics_enabled') === 'on',
    store_ready: data.get('store_ready') === 'on',
  }
}

function brandingPatchFromForm(form: HTMLFormElement): ChannelBrandingUpdate {
  const data = new FormData(form)
  return {
    display_name: trimOptional(data.get('display_name')),
    short_name: trimOptional(data.get('short_name')),
    color: trimOptional(data.get('color')),
    logo_text: trimOptional(data.get('logo_text')),
    logo_url: trimOptional(data.get('logo_url')),
  }
}

function StationConfigPanel({
  config,
  saving,
  error,
  onSave,
}: {
  config: StationAppConfig | undefined
  saving: boolean
  error: unknown
  onSave: (patch: StationAppConfigUpdate) => void
}) {
  if (!config) {
    return (
      <section
        className="rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="m-0 text-lg font-semibold">Station app config</h2>
        <div className="mt-2 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Loading app config.</div>
      </section>
    )
  }
  return (
    <section
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="m-0 text-lg font-semibold">Station app config</h2>
        <span className="cc-mono rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
          {config.build_profile.tier}
        </span>
      </div>
      <form
        key={`${config.generated_at}-station`}
        className="mt-4 grid gap-3 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          onSave(stationPatchFromForm(event.currentTarget))
        }}
      >
        <label className="grid gap-1 text-sm" htmlFor="station-name">
          <span className="font-semibold">Station name</span>
          <input
            id="station-name"
            name="station_name"
            defaultValue={config.station_name}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="app-name">
          <span className="font-semibold">App name</span>
          <input
            id="app-name"
            name="app_name"
            defaultValue={config.build_profile.app_name}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="default-channel">
          <span className="font-semibold">Default channel</span>
          <select
            id="default-channel"
            name="default_channel_id"
            defaultValue={config.default_channel_id}
            className={fieldClass}
            style={fieldStyle}
          >
            {config.channels.map((channel) => (
              <option key={channel.channel_id} value={channel.channel_id}>
                {channel.branding.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm" htmlFor="build-tier">
          <span className="font-semibold">Build tier</span>
          <select
            id="build-tier"
            name="build_tier"
            defaultValue={config.build_profile.tier}
            className={fieldClass}
            style={fieldStyle}
          >
            <option value="unbranded">Unbranded</option>
            <option value="branded">Branded</option>
          </select>
        </label>
        <label className="grid gap-1 text-sm" htmlFor="support-url">
          <span className="font-semibold">Support URL</span>
          <input
            id="support-url"
            name="support_url"
            defaultValue={config.support_url}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="privacy-url">
          <span className="font-semibold">Privacy URL</span>
          <input
            id="privacy-url"
            name="privacy_url"
            defaultValue={config.privacy_url}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            name="analytics_enabled"
            type="checkbox"
            defaultChecked={config.analytics_enabled}
          />
          <span>Analytics enabled</span>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            name="store_ready"
            type="checkbox"
            defaultChecked={config.build_profile.store_ready}
          />
          <span>Store ready</span>
        </label>
        <div className="md:col-span-2 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: saving ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: saving ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            Save station config
          </button>
          {Boolean(error) && (
            <span role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
              {apiMessage(error, 'Station config save failed.')}
            </span>
          )}
        </div>
      </form>
    </section>
  )
}

function ChannelBrandingPanel({
  channel,
  saving,
  error,
  onSave,
}: {
  channel: ChannelPublicConfig | undefined
  saving: boolean
  error: unknown
  onSave: (channelId: string, patch: ChannelBrandingUpdate) => void
}) {
  if (!channel) {
    return (
      <section
        className="rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        <h2 className="m-0 text-lg font-semibold">Channel branding</h2>
        <div className="mt-2 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Select a channel.</div>
      </section>
    )
  }
  return (
    <section
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div
          className="flex h-10 w-10 items-center justify-center rounded-md text-xs font-bold"
          style={{ background: channel.branding.color, color: 'white' }}
        >
          {channel.branding.logo_text}
        </div>
        <h2 className="m-0 text-lg font-semibold">Channel branding</h2>
      </div>
      <form
        key={`${channel.channel_id}-${channel.branding.display_name}`}
        className="mt-4 grid gap-3 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          onSave(channel.channel_id, brandingPatchFromForm(event.currentTarget))
        }}
      >
        <label className="grid gap-1 text-sm" htmlFor="channel-display-name">
          <span className="font-semibold">Display name</span>
          <input
            id="channel-display-name"
            name="display_name"
            defaultValue={channel.branding.display_name}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="channel-short-name">
          <span className="font-semibold">Short name</span>
          <input
            id="channel-short-name"
            name="short_name"
            defaultValue={channel.branding.short_name}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="channel-color">
          <span className="font-semibold">Color</span>
          <input
            id="channel-color"
            name="color"
            type="color"
            defaultValue={channel.branding.color}
            className="h-10 w-full rounded-md px-2 py-1"
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="channel-logo-text">
          <span className="font-semibold">Logo text</span>
          <input
            id="channel-logo-text"
            name="logo_text"
            defaultValue={channel.branding.logo_text}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <label className="grid gap-1 text-sm md:col-span-2" htmlFor="channel-logo-url">
          <span className="font-semibold">Logo URL</span>
          <input
            id="channel-logo-url"
            name="logo_url"
            defaultValue={channel.branding.logo_url ?? ''}
            className={fieldClass}
            style={fieldStyle}
          />
        </label>
        <div className="md:col-span-2 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: saving ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: saving ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            Save channel branding
          </button>
          {Boolean(error) && (
            <span role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
              {apiMessage(error, 'Channel branding save failed.')}
            </span>
          )}
        </div>
      </form>
    </section>
  )
}

function PlayoutPanel({ nowNext }: { nowNext: ChannelNowNext | undefined }) {
  if (!nowNext) {
    return (
      <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
        <div className="text-sm font-semibold">Now / next</div>
        <div className="mt-2 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Select a channel to load playout state.</div>
      </section>
    )
  }
  const blocks = [nowNext.current, nowNext.next].filter((block): block is PlayoutBlock => block != null)
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Now / next</h2>
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {nowNext.proof_boundary}
          </div>
        </div>
        {nowNext.fallback_active && (
          <span className="rounded-full px-2 py-1 text-xs font-semibold" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
            Fallback active
          </span>
        )}
      </div>
      <div className="mt-4 grid gap-3">
        {blocks.map((block) => (
          <div
            key={block.block_id}
            className="grid gap-2 rounded-md p-3 sm:grid-cols-[1fr_auto]"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{block.title}</span>
                <StatusPill label={block.status ?? 'scheduled'} />
              </div>
              <div className="cc-mono mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                {block.kind} / {block.source_ref}
              </div>
              {block.failover_reason && (
                <div className="mt-2 text-xs" style={{ color: 'var(--cc-err)' }}>
                  Failed over from {block.failover_from}: {block.failover_reason}
                </div>
              )}
            </div>
            <div className="cc-mono text-right text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              {formatTime(block.starts_at)}
              <div>{Math.round(block.duration_seconds / 60)} min</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function OutputsPanel({ outputs }: { outputs: ChannelOutput[] }) {
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <h2 className="m-0 text-lg font-semibold">Software outputs</h2>
      <div className="mt-3 grid gap-3">
        {outputs.map((output) => (
          <div
            key={`${output.kind}-${output.target}`}
            className="rounded-md p-3 text-sm"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{output.label}</span>
              <span className="cc-mono rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {output.kind}
              </span>
            </div>
            <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>{output.target}</div>
            <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>{output.next_step}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

function formatMeasured(value: number | null | undefined, unit: string): string {
  return value == null ? 'Not measured yet' : `${value} ${unit}`
}

export function EgressControlPanel({
  channelId,
  state,
  health,
  pendingCommand,
  canControl,
  error,
  onCommand,
}: {
  channelId: string | undefined
  state: EgressStateRow | null | undefined
  health: EgressHealthSample[]
  pendingCommand: { channelId: string; action: EgressCommandAction } | null
  canControl: boolean
  error: unknown
  onCommand: (action: EgressCommandAction) => void
}) {
  const latestHealth = health[0]
  const sending = pendingCommand !== null
  const commandDisabled = !channelId || sending || !canControl
  const rawEgressState = state?.state ?? 'STOPPED'
  // Tone comes from the shared toneForEgressState so this pill cannot disagree
  // with the same feed's pill on System Health. A not-on-air feed is amber
  // (attention), not the blue "info" this panel used to fall back to.
  const egressStateTone = EGRESS_TONE_STYLE[toneForEgressState(rawEgressState)]
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Outgoing channel feed</h2>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {channelId ? `Start or stop the local worker that sends ${channelId} to configured outputs.` : 'Select a channel to control its outgoing feed.'}
          </div>
        </div>
        <span
          className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold"
          style={{ background: egressStateTone.bg, color: egressStateTone.fg }}
        >
          {stateLabel(rawEgressState, 'Stopped')}
        </span>
      </div>
      <div className="mt-3 grid gap-2 text-sm">
        <div className="cc-mono text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          State: {stateLabel(rawEgressState, 'Stopped')}
          {state?.pid ? ` / pid ${state.pid}` : ''}
        </div>
        {state?.current_source_label && (
          <div style={{ color: 'var(--cc-ink-2)' }}>Source: {state.current_source_label}</div>
        )}
        {state?.last_error && (
          <div role="alert" style={{ color: 'var(--cc-err)' }}>{state.last_error}</div>
        )}
        {latestHealth && (
          <dl className="m-0 grid gap-2 text-xs sm:grid-cols-2" style={{ color: 'var(--cc-ink-3)' }}>
            <div>
              <dt className="font-semibold">On air</dt>
              <dd className="m-0">{humanizeDuration(latestHealth.seconds_on_air)}</dd>
            </div>
            <div>
              <dt className="font-semibold">Encoder</dt>
              <dd className="m-0">{formatMeasured(latestHealth.encoder_fps, 'fps')}</dd>
            </div>
            <div>
              <dt className="font-semibold">Bitrate</dt>
              <dd className="m-0">{formatMeasured(latestHealth.encoder_bitrate_kbps, 'kbps')}</dd>
            </div>
            <div>
              <dt className="font-semibold">Dropped frames</dt>
              <dd className="m-0">{latestHealth.dropped_frames}</dd>
            </div>
            <div>
              <dt className="font-semibold">Loudness</dt>
              <dd className="m-0">{formatMeasured(latestHealth.last_loudness_lufs, 'LUFS')}</dd>
            </div>
            <div>
              <dt className="font-semibold">Captions</dt>
              <dd className="m-0">
                {latestHealth.caption_status === 'on' ? 'On' : 'Not yet confirmed (waiting for the on-air check)'}
              </dd>
            </div>
          </dl>
        )}
        {latestHealth && Object.keys(latestHealth.sink_connected).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(latestHealth.sink_connected).map(([sink, connected]) => (
              <span
                key={sink}
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                style={{
                  background: connected ? 'var(--cc-ok-soft)' : 'var(--cc-err-soft)',
                  color: connected ? 'var(--cc-ok)' : 'var(--cc-err)',
                }}
              >
                {sink}: {connected ? 'connected' : 'not connected'}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        {([
          ['start', 'Start'],
          ['stop', 'Stop'],
          ['reload', 'Restart feed'],
          ['drain', 'Finish current item, then stop'],
        ] as const).map(([action, label]) => {
          const isThisSending =
            pendingCommand?.channelId === channelId &&
            pendingCommand?.action === action
          return (
            <button
              key={action}
              type="button"
              disabled={commandDisabled}
              onClick={() => onCommand(action)}
              className="rounded-md px-3 py-2 text-sm font-semibold"
              style={{
                background: commandDisabled ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
                color: commandDisabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
              }}
            >
              {isThisSending ? 'Queuing...' : label}
            </button>
          )
        })}
      </div>
      {Boolean(error) && (
        <div role="alert" className="mt-3 text-sm" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Channel command failed.')}
        </div>
      )}
      {!canControl && (
        <div role="alert" className="mt-3 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          Outgoing feed controls require the meeting operator role.
        </div>
      )}
    </section>
  )
}

function EgressConfigPanel({
  channelId,
  config,
  loadError,
  saving,
  canEdit,
  saveError,
  onSave,
  configured,
}: {
  channelId: string | undefined
  config: EgressConfig | undefined
  loadError: unknown
  saving: boolean
  canEdit: boolean
  saveError: unknown
  onSave: (next: EgressConfig) => void
  configured: boolean
}) {
  const [autoStart, setAutoStart] = useState<boolean | null>(null)
  const [allowSoftwareFallback, setAllowSoftwareFallback] = useState<boolean | null>(null)
  const [fillPolicy, setFillPolicy] = useState<'slate' | 'bulletins' | null>(null)
  const [slateMessage, setSlateMessage] = useState<string | null>(null)
  const [ndiName, setNdiName] = useState<string | null>(null)
  const [sdiDevice, setSdiDevice] = useState<string | null>(null)

  // Edits layer over the fetched config; null means "not touched yet".
  const effectiveAutoStart = autoStart ?? config?.auto_start ?? false
  const effectiveAllowSoftwareFallback =
    allowSoftwareFallback ?? config?.allow_software_fallback ?? false
  const effectiveFillPolicy = fillPolicy ?? config?.fill_policy ?? 'slate'
  const effectiveSlateMessage = slateMessage ?? config?.slate_message ?? ''
  const effectiveNdiName = ndiName ?? config?.ndi_relay_name ?? ''
  const effectiveSdiDevice = sdiDevice ?? config?.sdi_relay_device ?? ''
  const dirty =
    config != null &&
    (effectiveAutoStart !== (config.auto_start ?? false) ||
      effectiveAllowSoftwareFallback !== (config.allow_software_fallback ?? false) ||
      effectiveFillPolicy !== (config.fill_policy ?? 'slate') ||
      effectiveSlateMessage !== config.slate_message ||
      effectiveNdiName !== (config.ndi_relay_name ?? '') ||
      effectiveSdiDevice !== (config.sdi_relay_device ?? ''))

  const notFound = loadError instanceof ApiError && loadError.status === 404
  const notConfigured = Boolean(channelId) && !configured

  return (
    <section
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      aria-label="Channel automation settings"
    >
      <h2 className="m-0 text-lg font-semibold">Run this channel 24/7</h2>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        {channelId
          ? `Automation settings for ${channelId}. Saved settings survive restarts.`
          : 'Select a channel to edit its automation settings.'}
      </div>

      {(notFound || notConfigured) && (
        <div
          className="mt-3 rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
        >
          This channel has no outgoing-feed configuration yet. Create one from
          the channel egress runbook (or the setup flow) first; then automation
          settings appear here.
        </div>
      )}
      {Boolean(loadError) && !notFound && (
        <div role="alert" className="mt-3 text-sm" style={{ color: 'var(--cc-err)' }}>
          {apiMessage(loadError, 'Could not load the channel configuration.')}
        </div>
      )}

      {config && (
        <div className="mt-3 grid gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={effectiveAutoStart}
              disabled={!canEdit}
              onChange={(e) => setAutoStart(e.target.checked)}
            />
            <span>
              <span className="font-medium">Keep this channel on air</span>
              <span className="block text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                Starts the feed automatically after restarts and crashes.
              </span>
            </span>
          </label>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={effectiveAllowSoftwareFallback}
              disabled={!canEdit}
              onChange={(e) => setAllowSoftwareFallback(e.target.checked)}
            />
            <span>
              <span className="font-medium">Allow software (CPU) encoding fallback</span>
              <span className="block text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                When no hardware video encoder is present, encode H.264 on the CPU (slower).
                Applies to H.264 only &mdash; HEVC/H.265 always requires a hardware encoder.
              </span>
            </span>
          </label>

          <fieldset className="m-0 border-0 p-0">
            <legend
              className="mb-2 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Between programs, show
            </legend>
            <RadioCardGroup
              label="Filler between programs"
              options={[
                {
                  id: 'slate' as const,
                  label: 'Station slate',
                  description: 'A quiet branded card with your station message.',
                },
                {
                  id: 'bulletins' as const,
                  label: 'Community bulletins',
                  description: 'Rotates approved bulletin-board slides; falls back to slate when none are approved.',
                },
              ]}
              value={effectiveFillPolicy}
              onChange={(v) => {
                if (canEdit) setFillPolicy(v)
              }}
              className="grid grid-cols-2 gap-2"
            />
          </fieldset>

          <label className="block">
            <span
              className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Slate message
            </span>
            <input
              type="text"
              value={effectiveSlateMessage}
              disabled={!canEdit}
              onChange={(e) => setSlateMessage(e.target.value)}
              className={fieldClass + ' w-full'}
              style={fieldStyle}
            />
          </label>

          <label className="block">
            <span
              className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              NDI output name (optional)
            </span>
            <input
              type="text"
              value={effectiveNdiName}
              disabled={!canEdit}
              onChange={(e) => setNdiName(e.target.value)}
              placeholder="e.g. CivicCast Public"
              className={fieldClass + ' w-full'}
              style={fieldStyle}
            />
            <span className="mt-1 block text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              Blank = no NDI output. Bring-your-own NDI: requires the
              station&apos;s NDI-capable FFmpeg build (CIVICCAST_NDI_FFMPEG). The
              channel&apos;s output republishes under this name; see the NDI
              runbook section.
            </span>
          </label>

          <label className="block">
            <span
              className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              SDI output device (optional)
            </span>
            <input
              type="text"
              value={effectiveSdiDevice}
              disabled={!canEdit}
              onChange={(e) => setSdiDevice(e.target.value)}
              placeholder="e.g. DeckLink Mini Monitor 4K"
              className={fieldClass + ' w-full'}
              style={fieldStyle}
            />
            <span className="mt-1 block text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              Blank = no SDI output. Bring-your-own SDI: requires the
              station&apos;s DeckLink-capable FFmpeg build (CIVICCAST_SDI_FFMPEG)
              and card. Use the exact device name that &quot;ffmpeg -sinks
              decklink&quot; reports; see the SDI runbook section (or the OBS
              bridge if you don&apos;t build FFmpeg).
            </span>
          </label>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canEdit || !dirty || saving}
              onClick={() =>
                onSave({
                  ...config,
                  auto_start: effectiveAutoStart,
                  allow_software_fallback: effectiveAllowSoftwareFallback,
                  fill_policy: effectiveFillPolicy,
                  slate_message: effectiveSlateMessage,
                  ndi_relay_name: effectiveNdiName.trim() ? effectiveNdiName.trim() : null,
                  sdi_relay_device: effectiveSdiDevice.trim() ? effectiveSdiDevice.trim() : null,
                })
              }
              className="rounded-md px-3 py-2 text-sm font-semibold"
              style={{
                background:
                  !canEdit || !dirty || saving ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
                color:
                  !canEdit || !dirty || saving ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
              }}
            >
              {saving ? 'Saving…' : 'Save automation settings'}
            </button>
            {dirty && !saving && (
              <span className="text-[11px]" style={{ color: 'var(--cc-warn)' }}>
                Unsaved changes
              </span>
            )}
          </div>
          {Boolean(saveError) && (
            <div role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
              {apiMessage(saveError, 'Could not save the automation settings.')}
            </div>
          )}
          {!canEdit && (
            <div className="text-sm" style={{ color: 'var(--cc-ink-3)' }}>
              Automation settings require the setup admin role.
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function HeadendDeliveryPanel({
  channelId,
  profiles,
  config,
  applying,
  canEdit,
  applyError,
  onApply,
  verifying,
  verifyResult,
  verifyError,
  onVerify,
}: {
  channelId: string | undefined
  profiles: HeadendProfile[]
  config: EgressConfig | undefined
  applying: boolean
  canEdit: boolean
  applyError: unknown
  onApply: (payload: {
    profile_id: string
    destination_uri: string
    muxrate_kbps: number | null
    keep_existing_sinks: boolean
  }) => void
  verifying: boolean
  verifyResult: ComplianceProbeResult | undefined
  verifyError: unknown
  onVerify: () => void
}) {
  const [profileId, setProfileId] = useState<string>('')
  const [destination, setDestination] = useState('')
  const [muxrate, setMuxrate] = useState('')
  const [keepSinks, setKeepSinks] = useState(false)

  const effectiveProfileId = profileId || profiles[0]?.profile_id || ''
  const selected = profiles.find((p) => p.profile_id === effectiveProfileId)
  const isFileDrop = selected?.transport === 'file-drop'
  const headendSink = (config?.sinks ?? []).find(
    (sink) => sink.label === 'Cable headend' || sink.kind === 'udp-ts',
  )
  const disabled =
    !canEdit || applying || !channelId || !selected || !destination.trim()

  return (
    <section
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      aria-label="Cable headend delivery"
    >
      <h2 className="m-0 text-lg font-semibold">Cable headend delivery</h2>
      <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Named presets built from published vendor specs. Pick yours, paste the
        destination from your carriage agreement, apply.
      </div>

      <div className="mt-3 grid gap-3">
        <label className="block">
          <span
            className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            Headend preset
          </span>
          <select
            value={effectiveProfileId}
            onChange={(e) => setProfileId(e.target.value)}
            disabled={!canEdit}
            className={fieldClass + ' w-full'}
            style={fieldStyle}
          >
            {profiles.map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        {selected && (
          <div
            className="rounded-md p-2 text-[11px]"
            style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
          >
            <div>
              {selected.vendor} · {selected.canonical_profile.video_codec} ·{' '}
              {selected.canonical_profile.width}×{selected.canonical_profile.height}
              {selected.muxrate_kbps ? ` · mux ${selected.muxrate_kbps} kbps` : ''}
            </div>
            {(selected.operator_must_supply ?? []).map((item) => (
              <div key={item} className="mt-1" style={{ color: 'var(--cc-warn)' }}>
                You supply: {item}
              </div>
            ))}
            {(selected.not_claimed ?? []).map((item) => (
              <div key={item} className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                {item}
              </div>
            ))}
          </div>
        )}

        <label className="block">
          <span
            className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            {isFileDrop ? 'Drop folder / file path' : 'Destination (udp://address:port)'}
          </span>
          <input
            type="text"
            value={destination}
            disabled={!canEdit}
            onChange={(e) => setDestination(e.target.value)}
            placeholder={isFileDrop ? 'file:///D:/headend-drop/channel.ts' : 'udp://239.255.0.1:5000'}
            className={fieldClass + ' w-full'}
            style={fieldStyle}
          />
        </label>

        {!isFileDrop && (
          <label className="block">
            <span
              className="mb-1 block text-[11px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Mux rate override (kbps, optional)
            </span>
            <input
              type="number"
              min={1}
              value={muxrate}
              disabled={!canEdit}
              onChange={(e) => setMuxrate(e.target.value)}
              placeholder={selected ? String(selected.muxrate_kbps) : ''}
              className={fieldClass + ' w-full'}
              style={fieldStyle}
            />
          </label>
        )}

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={keepSinks}
            disabled={!canEdit}
            onChange={(e) => setKeepSinks(e.target.checked)}
          />
          <span>Keep the channel&apos;s other outputs alongside the headend feed</span>
        </label>

        <div>
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              selected &&
              onApply({
                profile_id: selected.profile_id,
                destination_uri: destination.trim(),
                muxrate_kbps: muxrate.trim() ? Number(muxrate) : null,
                keep_existing_sinks: keepSinks,
              })
            }
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: disabled ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: disabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            {applying ? 'Applying…' : 'Apply headend preset'}
          </button>
        </div>

        {headendSink && (
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
            Current headend output: {headendSink.kind} → {headendSink.uri}
          </div>
        )}

        {headendSink?.kind === 'udp-ts' && (
          <div className="grid gap-2">
            <div>
              <button
                type="button"
                disabled={!canEdit || verifying}
                onClick={onVerify}
                className="rounded-md px-3 py-2 text-sm font-medium"
                style={{
                  border: '1px solid var(--cc-line)',
                  color: 'var(--cc-ink-2)',
                  background: 'var(--cc-surface)',
                }}
              >
                {verifying ? 'Verifying… (about 10s)' : 'Verify stream (TSDuck)'}
              </button>
            </div>
            {verifyResult && (
              <div
                className="rounded-md p-2 text-[11px]"
                style={{
                  background:
                    verifyResult.verdict === 'pass'
                      ? 'var(--cc-ok-soft)'
                      : verifyResult.verdict === 'fail'
                        ? 'var(--cc-err-soft)'
                        : 'var(--cc-surface-2)',
                  color: 'var(--cc-ink)',
                }}
              >
                <div className="font-semibold">
                  Verification: {verifyResult.verdict}
                  {verifyResult.tsduck_version ? ` · ${verifyResult.tsduck_version}` : ''}
                </div>
                {verifyResult.detail && <div className="mt-1">{verifyResult.detail}</div>}
                {(verifyResult.not_claimed ?? []).map((item) => (
                  <div key={item} className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                    Not claimed: {item}
                  </div>
                ))}
                {(verifyResult.checks ?? []).map((check) => (
                  <div key={check.check} className="cc-mono mt-0.5">
                    {check.check}: {check.status} — {check.detail}
                  </div>
                ))}
              </div>
            )}
            {Boolean(verifyError) && (
              <div role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
                {apiMessage(verifyError, 'Could not run the verification.')}
              </div>
            )}
          </div>
        )}
        {Boolean(applyError) && (
          <div role="alert" className="text-sm" style={{ color: 'var(--cc-err)' }}>
            {apiMessage(applyError, 'Could not apply the headend preset.')}
          </div>
        )}
        {!canEdit && (
          <div className="text-sm" style={{ color: 'var(--cc-ink-3)' }}>
            Headend delivery requires the setup admin role.
          </div>
        )}
      </div>
    </section>
  )
}

export function PlayoutPlanPanel({ plan }: { plan: ChannelPlayoutPlan | undefined }) {
  const blocks = plan?.blocks ?? []
  const gaps = plan?.gap_blocks ?? []
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Playout plan</h2>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {plan?.proof_boundary ?? 'Loading schedule-to-playout plan...'}
          </div>
        </div>
        {plan && (
          <span className="cc-mono rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            {plan.source}
          </span>
        )}
      </div>
      <div className="mt-3 grid gap-2">
        {blocks.map((block) => (
          <div key={block.block_id} className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{block.title}</span>
              <StatusPill label={block.status ?? 'scheduled'} />
              <span className="cc-mono rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {block.kind}
              </span>
            </div>
            <div className="cc-mono mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              {formatTime(block.starts_at)} / {Math.round(block.duration_seconds / 60)} min / {block.source_ref}
            </div>
          </div>
        ))}
      </div>
      {gaps.length > 0 && (
        <div className="mt-3 rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          <div className="font-semibold">Slate gaps</div>
          <div className="mt-1 grid gap-1">
            {gaps.map((gap) => (
              <div key={gap.block_id}>
                {formatTime(gap.starts_at)} for {Math.round(gap.duration_seconds / 60)} min using {gap.source_ref}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function ProofPanel({ proof }: { proof: ChannelProofLog | undefined }) {
  const events = proof?.events ?? []
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Proof log</h2>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Scheduled versus actual playout, including failover.
          </div>
        </div>
        {proof && (
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {proof.export_formats.join(' / ')}
          </div>
        )}
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[680px] border-collapse text-left text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--cc-line)' }}>
              <th className="px-2 py-2 font-semibold">Observed</th>
              <th className="px-2 py-2 font-semibold">Program</th>
              <th className="px-2 py-2 font-semibold">Actual</th>
              <th className="px-2 py-2 font-semibold">Captions</th>
              <th className="px-2 py-2 font-semibold">Machine summary</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.event_id} style={{ borderBottom: '1px solid var(--cc-line)' }}>
                <td className="px-2 py-2 cc-mono text-xs">{formatTime(event.observed_at)}</td>
                <td className="px-2 py-2">{event.title}</td>
                <td className="px-2 py-2"><StatusPill label={event.actual_status} /></td>
                <td className="px-2 py-2">{event.captions_attached ? 'Attached' : 'Missing'}</td>
                <td className="px-2 py-2 cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                  {event.machine_summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {proof && (
        <div className="mt-3 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Not claimed: {proof.not_claimed.join('; ')}
        </div>
      )}
    </section>
  )
}

function CtvPanel({ feed }: { feed: CtvFeed | undefined }) {
  const items = feed?.items ?? []
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Reference CTV feed</h2>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>{feed?.proof_boundary ?? 'Loading feed contract...'}</div>
        </div>
        <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
          {items.length} items
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {items.map((item) => (
          <div key={item.id} className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{item.title}</span>
              <span className="cc-mono rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {item.type}
              </span>
            </div>
            <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>{item.content_id}</div>
            <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>{item.description}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function ChannelOpsScreen() {
  const queryClient = useQueryClient()
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null)
  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    refetchInterval: POLL_MS,
  })
  const appConfigQuery = useQuery({
    queryKey: ['app-platform-config'],
    queryFn: getAppPlatformConfig,
    refetchInterval: POLL_MS,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
  })
  const appChannelById = useMemo<AppChannelMap>(() => {
    return new Map((appConfigQuery.data?.channels ?? []).map((channel) => [channel.channel_id, channel]))
  }, [appConfigQuery.data?.channels])
  const selectedChannel = useMemo(() => {
    const channels = channelsQuery.data ?? []
    return channels.find((channel) => channel.channel_id === selectedChannelId) ?? channels[0]
  }, [channelsQuery.data, selectedChannelId])
  const channelId = selectedChannel?.channel_id
  const selectedAppChannel = channelId ? appChannelById.get(channelId) : undefined
  // Outgoing-feed commands are live one-click actions; they stage a
  // confirmation here first (same copy as System Health's readiness panel).
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  const stationMutation = useMutation({
    mutationFn: updateAppPlatformConfig,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['app-platform-config'] })
    },
  })
  const brandingMutation = useMutation({
    mutationFn: ({ channelId, patch }: { channelId: string; patch: ChannelBrandingUpdate }) =>
      updateAppPlatformChannelBranding(channelId, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['app-platform-config'] })
    },
  })
  const nowNextQuery = useQuery({
    queryKey: ['channel-now-next', channelId],
    queryFn: () => getChannelNowNext(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const proofQuery = useQuery({
    queryKey: ['channel-proof-log', channelId],
    queryFn: () => getChannelProofLog(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const playoutPlanQuery = useQuery({
    queryKey: ['channel-playout-plan', channelId],
    queryFn: () => getChannelPlayoutPlan(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const egressStateQuery = useQuery({
    queryKey: ['egress-state', channelId],
    queryFn: () => getEgressState(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const egressHealthQuery = useQuery({
    queryKey: ['egress-health', channelId],
    queryFn: () => getEgressHealth(channelId ?? ''),
    enabled: Boolean(channelId),
    refetchInterval: POLL_MS,
  })
  const egressChannelsQuery = useQuery({
    queryKey: ['egress-channels'],
    queryFn: listEgressChannels,
    refetchInterval: POLL_MS,
    retry: false,
  })
  const egressConfigured = useMemo(() => {
    return Boolean(
      channelId &&
        (egressChannelsQuery.data ?? []).some((channel) => channel.channel_id === channelId),
    )
  }, [channelId, egressChannelsQuery.data])
  const egressCommandMutation = useMutation({
    mutationFn: ({ channelId, action }: { channelId: string; action: EgressCommandAction }) =>
      queueEgressCommand(channelId, action),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['egress-state', variables.channelId] })
      void queryClient.invalidateQueries({ queryKey: ['egress-health', variables.channelId] })
    },
  })
  const egressConfigQuery = useQuery({
    queryKey: ['egress-config', channelId],
    queryFn: () => getEgressConfig(channelId ?? ''),
    enabled: Boolean(channelId) && egressConfigured,
    retry: false,
  })
  const egressConfigMutation = useMutation({
    mutationFn: (next: EgressConfig) => updateEgressConfig(next.channel_id, next),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['egress-config', variables.channel_id] })
    },
  })
  const headendProfilesQuery = useQuery({
    queryKey: ['headend-profiles'],
    queryFn: listHeadendProfiles,
    retry: false,
  })
  const headendApplyMutation = useMutation({
    mutationFn: (payload: {
      profile_id: string
      destination_uri: string
      muxrate_kbps: number | null
      keep_existing_sinks: boolean
    }) => applyHeadendProfile(channelId ?? '', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['egress-config', channelId] })
    },
  })
  const complianceProbeMutation = useMutation({
    mutationFn: () => runComplianceProbe(channelId ?? ''),
  })
  const ctvQuery = useQuery({
    queryKey: ['ctv-feed', appConfigQuery.data?.station_name ?? 'operator'],
    queryFn: () => getCtvFeed(appConfigQuery.data?.station_name ?? 'CivicCast station'),
    refetchInterval: POLL_MS,
  })
  const error = channelsQuery.error ?? appConfigQuery.error ?? nowNextQuery.error ?? proofQuery.error ?? playoutPlanQuery.error ?? egressStateQuery.error ?? egressHealthQuery.error ?? egressChannelsQuery.error ?? ctvQuery.error
  // Fail closed while identity is loading or errored. The backend role gates
  // still enforce, but the operator UI should never present privileged channel
  // actions as enabled until the role is known.
  const canControlEgress =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'meeting_operator')
  const canEditEgressConfig =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'setup_admin')
  // Committing/rolling back an airing is fail-closed (matches the backend
  // require_any_role gate): disabled until the identity confirms the role.
  const canManageAir =
    staffIdentityQuery.isSuccess &&
    (hasOperatorRole(staffIdentityQuery.data, 'publish_operator') ||
      hasOperatorRole(staffIdentityQuery.data, 'setup_admin'))
  // Live takeover (S5): fail-closed, matching the API role split.
  const canManageTakeover =
    staffIdentityQuery.isSuccess &&
    (hasOperatorRole(staffIdentityQuery.data, 'meeting_operator') ||
      hasOperatorRole(staffIdentityQuery.data, 'setup_admin'))
  const canViewTakeoverAudit =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'setup_admin')

  return (
    <div className="grid gap-5 px-6 py-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">Channels</h1>
          <p className="m-0 mt-1 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Monitor linear channel identity, current playout, fallback behavior, proof logs, and CTV feed readiness.
          </p>
        </div>
        <div
          role="status"
          className="cc-mono rounded-full px-2.5 py-1 text-[11px]"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)', border: '1px solid var(--cc-line)' }}
        >
          refreshes every 30s
        </div>
      </header>

      {error && <ErrorPanel error={error} />}

      <section className="grid gap-3 lg:grid-cols-3" aria-label="Channel lineup">
        {(channelsQuery.data ?? []).map((channel) => (
          <ChannelCard
            key={channel.channel_id}
            channel={channel}
            appChannel={appChannelById.get(channel.channel_id)}
            active={channel.channel_id === selectedChannel?.channel_id}
            onSelect={setSelectedChannelId}
          />
        ))}
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="grid gap-4">
          <StationConfigPanel
            config={appConfigQuery.data}
            saving={stationMutation.isPending}
            error={stationMutation.error}
            onSave={(patch) => stationMutation.mutate(patch)}
          />
          <PlayoutPanel nowNext={nowNextQuery.data} />
          <CommitToAirPanel channelId={channelId} canManage={canManageAir} />
          <PlayoutPlanPanel plan={playoutPlanQuery.data} />
          <ProofPanel proof={proofQuery.data} />
        </div>
        <div className="grid content-start gap-4">
          <ChannelBrandingPanel
            channel={selectedAppChannel}
            saving={brandingMutation.isPending}
            error={brandingMutation.error}
            onSave={(channelId, patch) => brandingMutation.mutate({ channelId, patch })}
          />
          <EgressControlPanel
            channelId={channelId}
            state={egressStateQuery.data}
            health={egressHealthQuery.data ?? []}
            pendingCommand={egressCommandMutation.isPending ? (egressCommandMutation.variables ?? null) : null}
            canControl={canControlEgress}
            error={egressCommandMutation.error}
            onCommand={(action) => {
              if (!channelId) return
              const channelName = selectedChannel?.branding.display_name ?? channelId
              setPendingConfirm({
                ...feedCommandConfirmCopy(action, channelName),
                run: () => egressCommandMutation.mutate({ channelId, action }),
              })
            }}
          />
          <TakeoverCard
            channelId={channelId}
            canManage={canManageTakeover}
            canViewAudit={canViewTakeoverAudit}
          />
          <CableVerificationCard />
          {channelId && <LoudnessPlanCard channelId={channelId} enabled={egressConfigured} />}
          {channelId && <CaptionStatusCard channelId={channelId} />}
          {channelId && <AudioTracksCard channelId={channelId} />}
          <HeadendDeliveryPanel
            key={`headend-${channelId ?? 'no-channel'}`}
            channelId={channelId}
            profiles={headendProfilesQuery.data ?? []}
            config={egressConfigQuery.data}
            applying={headendApplyMutation.isPending}
            canEdit={canEditEgressConfig}
            applyError={headendApplyMutation.error}
            onApply={(payload) => headendApplyMutation.mutate(payload)}
            verifying={complianceProbeMutation.isPending}
            verifyResult={complianceProbeMutation.data}
            verifyError={complianceProbeMutation.error}
            onVerify={() => complianceProbeMutation.mutate()}
          />
          <EgressConfigPanel
            key={channelId ?? 'no-channel'}
            channelId={channelId}
            config={egressConfigQuery.data}
            loadError={egressConfigQuery.error}
            saving={egressConfigMutation.isPending}
            canEdit={canEditEgressConfig}
            saveError={egressConfigMutation.error}
            onSave={(next) => egressConfigMutation.mutate(next)}
            configured={egressConfigured}
          />
          <OutputsPanel outputs={selectedChannel?.outputs ?? []} />
          <CtvPanel feed={ctvQuery.data} />
        </div>
      </div>
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
