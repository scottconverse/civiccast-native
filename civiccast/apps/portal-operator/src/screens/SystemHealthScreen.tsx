import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import {
  ApiError,
  type EgressCommandAction,
  type EgressHealthSample,
  type EgressSchemaCurrency,
  type EgressStateRow,
  configureRollbackArtifact,
  createSupportBundle,
  downloadSupportBundle,
  getEgressHealth,
  getEgressSchemaCurrency,
  getEgressState,
  getRuntimeSafeToAir,
  getStaffIdentity,
  getRestoreStatus,
  getSystemHealth,
  getUpdateRollbackStatus,
  listChannelProfiles,
  openUpdateMaintenanceWindow,
  queueEgressCommand,
  repairGstreamerRuntime,
  runFailedUpdateRollbackRehearsal,
  runDisasterRecoveryDrill,
  runPostUpdateProof,
  runRollbackRehearsal,
  runRestoreRehearsal,
  runSelfTestNow,
  runUpdatePreflight,
  startFirstBroadcastRehearsal,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { humanizeDuration } from '../format'
import { readinessLabel, stateLabel, toneForEgressState, toneForReadiness } from './status-language'
import type {
  ChannelRuntimeStatus,
  DiagnosticBundleResponse,
  DrillReport,
  ChannelProfile,
  GstreamerRepairResponse,
  RehearsalReport,
  RestoreStatus,
  RuntimeSafeToAirStatus,
  SystemHealthCheck,
  SystemHealthReport,
  SystemResourceSample,
  SystemSelfTest,
  UpdateRollbackStatus,
} from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

const COLOR_TONE: Record<
  SystemHealthReport['safe_to_broadcast'],
  { bg: string; fg: string; border: string; label: string }
> = {
  green: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)', border: 'var(--cc-ok)', label: 'Ready' },
  // Label must match docs/operator-language-guide.md and the installer's
  // readiness label in civiccast/installer/service.py. "Check first" drifted
  // here and left the console contradicting the operator vocabulary.
  yellow: {
    bg: 'var(--cc-warn-soft)',
    fg: 'var(--cc-ink)',
    border: 'var(--cc-warn)',
    label: 'Check before meeting',
  },
  red: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)', border: 'var(--cc-err)', label: 'Do not broadcast yet' },
}

function HealthPill({ color }: { color: SystemHealthReport['safe_to_broadcast'] }) {
  const tone = COLOR_TONE[color]
  return (
    <span
      className="rounded-full px-3 py-1 text-xs font-semibold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.label}
    </span>
  )
}

function CheckRow({ check }: { check: SystemHealthCheck }) {
  const tone = COLOR_TONE[check.color]
  return (
    <article
      className="grid gap-2 rounded-md p-3 md:grid-cols-[1fr_auto]"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="m-0 text-sm font-semibold">{check.label}</h3>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
            style={{ background: tone.bg, color: tone.fg }}
          >
            {readinessLabel(check.state)}
          </span>
        </div>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {check.message}
        </p>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          <strong>Next step.</strong> {check.next_step}
        </p>
      </div>
      <div className="cc-mono text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
        {check.kind}
      </div>
    </article>
  )
}

function RehearsalPanel({ report }: { report: RehearsalReport }) {
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-info-soft)', border: '1px solid var(--cc-info)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Broadcast readiness check result</h2>
        <HealthPill color={report.safe_to_broadcast} />
      </div>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        This checks configuration, storage, and the bundled sample video -- it does not play
        video in this screen. Use Open resident preview to see what residents will see.
      </p>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        {report.message}
      </p>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        <strong>Next step.</strong> {report.next_step}
      </p>
      {(report.private_session_id || report.recording_asset_id || report.resident_preview_proof) && (
        <dl className="m-0 grid gap-2 text-xs sm:grid-cols-3" style={{ color: 'var(--cc-ink-3)' }}>
          {report.private_session_id && (
            <div>
              <dt className="font-semibold">Private session</dt>
              <dd className="m-0 cc-mono">{report.private_session_id}</dd>
            </div>
          )}
          {report.recording_asset_id && (
            <div>
              <dt className="font-semibold">Recording proof</dt>
              <dd className="m-0 cc-mono">{report.recording_asset_id}</dd>
            </div>
          )}
          {report.resident_preview_proof && (
            <div>
              <dt className="font-semibold">Resident preview</dt>
              <dd className="m-0">{report.resident_preview_proof}</dd>
            </div>
          )}
        </dl>
      )}
      {(report.evidence?.length ?? 0) > 0 && (
        <ul className="m-0 grid gap-1 pl-4 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {report.evidence?.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

function StatusPill({ label, tone }: { label: string; tone: 'ok' | 'warn' | 'err' }) {
  const colors = {
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
    err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
  }[tone]
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {label}
    </span>
  )
}

function runtimeChannelTone(color: ChannelRuntimeStatus['color']): 'ok' | 'warn' | 'err' {
  return color === 'green' ? 'ok' : color === 'red' ? 'err' : 'warn'
}

function runtimeChannelLabel(channel: ChannelRuntimeStatus): string {
  if (channel.color === 'red') return 'Needs attention'
  if (channel.color === 'yellow') return 'Working'
  return channel.on_air ? 'On air' : 'Ready'
}

// The headline live signal: is each channel that should be running actually on
// air and healthy *right now*? This is distinct from the install-time
// "safe to broadcast" readiness below — it reflects the running egress workers.
export function RuntimeSafeToAirBanner({
  status,
  onOpenAlerts,
}: {
  status: RuntimeSafeToAirStatus | undefined
  onOpenAlerts?: () => void
}) {
  if (!status) return null
  const tone = COLOR_TONE[status.color]
  const critical = status.active_critical_alerts ?? 0
  const warning = status.active_warning_alerts ?? 0
  const channels = status.channels ?? []
  return (
    <section
      aria-label="Runtime safe to air"
      // Live region: this banner polls every 5s, so announce a change (e.g. a
      // channel dropping off air) to screen readers — assertive when red.
      role="status"
      aria-live={status.color === 'red' ? 'assertive' : 'polite'}
      className="grid gap-3 rounded-md p-4"
      style={{ background: tone.bg, border: `2px solid ${tone.border}` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
            On air right now
          </div>
          <h2 className="m-0 text-xl font-semibold">{status.label}</h2>
          <p className="m-0 mt-1 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            {status.operator_message}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap justify-end gap-2">
            <StatusPill label={`${critical} critical`} tone={critical > 0 ? 'err' : 'ok'} />
            <StatusPill label={`${warning} warning`} tone={warning > 0 ? 'warn' : 'ok'} />
          </div>
          {onOpenAlerts && (
            <button
              type="button"
              onClick={onOpenAlerts}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            >
              {critical + warning > 0 ? 'Review alerts' : 'Open alerts'}
            </button>
          )}
        </div>
      </div>
      {channels.length === 0 ? (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No channels are set to run automatically, so there is nothing on air to watch yet.
        </p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {channels.map((channel) => (
            <div
              key={channel.channel_id}
              className="flex items-center justify-between gap-2 rounded-md p-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              <div className="min-w-0">
                <div className="cc-truncate text-sm font-semibold">{channel.channel_id}</div>
                <div className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                  {stateLabel(channel.egress_state)}
                  {channel.on_healthy_slate ? ' · on safety slate' : ''}
                </div>
              </div>
              <StatusPill label={runtimeChannelLabel(channel)} tone={runtimeChannelTone(channel.color)} />
            </div>
          ))}
        </div>
      )}
      <p className="m-0 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
        Live check {new Date(status.generated_at).toLocaleTimeString()}
      </p>
    </section>
  )
}

function selfTestTone(status: SystemSelfTest['status']): 'ok' | 'warn' | 'err' {
  return status === 'pass' ? 'ok' : status === 'fail' ? 'err' : 'warn'
}

const SELF_TEST_STATUS_LABEL: Record<SystemSelfTest['status'], string> = {
  pass: 'Passed',
  warn: 'Passed with warnings',
  fail: 'Found a problem',
}

// Plain-English names for the machine probe keys (non-technical operator).
const CHECK_LABEL: Record<string, string> = {
  readiness: 'Station readiness',
  filesink_continuity: 'Recording continuity',
  backup_probe: 'Backup',
  model_ping: 'AI engine',
  restore_rehearsal: 'Restore rehearsal',
  srt_continuity: 'SRT streaming',
  tsduck_probe: 'Cable verification',
  channel_test_send: 'Alert delivery ready',
}

function selfTestCheckLabel(name: string): string {
  return CHECK_LABEL[name] ?? name.replaceAll('_', ' ')
}

export function SelfTestPanel({
  selfTest,
  onRun,
  running,
  onRunWeekly,
  runningWeekly,
  canRun,
  error,
}: {
  selfTest: SystemSelfTest | null | undefined
  onRun?: () => void
  running?: boolean
  onRunWeekly?: () => void
  runningWeekly?: boolean
  canRun?: boolean
  error?: unknown
}) {
  const checks = selfTest ? Object.entries(selfTest.checks ?? {}) : []
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Latest self-check</h2>
        {selfTest && (
          <StatusPill label={SELF_TEST_STATUS_LABEL[selfTest.status]} tone={selfTestTone(selfTest.status)} />
        )}
      </div>
      {!selfTest ? (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          CivicCast has not run an automatic self-check yet. The first daily check runs overnight.
        </p>
      ) : (
        <>
          <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            {selfTest.summary}
          </p>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {selfTest.kind === 'weekly' ? 'Weekly' : 'Daily'} check
            {selfTest.finished_at
              ? ` · finished ${new Date(selfTest.finished_at).toLocaleString()}`
              : ' · still running'}
          </p>
          {checks.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {checks.map(([name, ok]) => (
                <StatusPill
                  key={name}
                  label={`${selfTestCheckLabel(name)}: ${ok ? 'ok' : 'failed'}`}
                  tone={ok ? 'ok' : 'err'}
                />
              ))}
            </div>
          )}
          {checks.length > 0 && (
            <p className="m-0 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              Checks whose tools aren&apos;t installed (e.g. cable verification, SRT) are skipped here, not failed.
            </p>
          )}
        </>
      )}
      {(onRun || onRunWeekly) && (
        <div className="flex flex-wrap gap-2">
          {onRun && (
            <button
              type="button"
              onClick={onRun}
              disabled={!canRun || running || runningWeekly}
              className="rounded-md px-3 py-2 text-sm font-semibold"
              style={{ background: canRun ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRun ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
            >
              {running ? 'Running self-check...' : 'Run daily self-check now'}
            </button>
          )}
          {onRunWeekly && (
            <button
              type="button"
              onClick={onRunWeekly}
              disabled={!canRun || running || runningWeekly}
              className="rounded-md px-3 py-2 text-sm font-semibold"
              style={{ background: 'var(--cc-surface-3)', color: canRun ? 'var(--cc-ink)' : 'var(--cc-ink-3)', border: '1px solid var(--cc-line)' }}
            >
              {runningWeekly ? 'Running self-check...' : 'Run weekly self-check now'}
            </button>
          )}
        </div>
      )}
      {(onRun || onRunWeekly) && !canRun && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Running a self-check requires setup admin or support admin.
        </p>
      )}
      {Boolean(error) && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Self-check could not run.')}
        </div>
      )}
    </section>
  )
}

function gbFree(value: number | null | undefined): string {
  return value == null ? 'Not measured yet' : `${value.toFixed(1)} GB free`
}

export function ResourceSnapshotPanel({ sample }: { sample: SystemResourceSample | null | undefined }) {
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="m-0 text-base font-semibold">Machine health</h2>
      {!sample ? (
        <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          No resource sample has been taken yet.
        </p>
      ) : (
        <>
          <dl className="m-0 grid gap-2 text-xs sm:grid-cols-2" style={{ color: 'var(--cc-ink-3)' }}>
            <div>
              <dt className="font-semibold">Processor</dt>
              <dd className="m-0">{sample.cpu_percent == null ? 'Not measured yet' : `${Math.round(sample.cpu_percent)}% busy`}</dd>
            </div>
            <div>
              <dt className="font-semibold">Memory</dt>
              <dd className="m-0">
                {sample.ram_used_gb == null || sample.ram_total_gb == null
                  ? 'Not measured yet'
                  : `${sample.ram_used_gb.toFixed(1)} / ${sample.ram_total_gb.toFixed(1)} GB used`}
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Media space</dt>
              <dd className="m-0">{gbFree(sample.media_volume_free_gb)}</dd>
            </div>
            <div>
              <dt className="font-semibold">Backup space</dt>
              <dd className="m-0">{gbFree(sample.backup_volume_free_gb)}</dd>
            </div>
            <div>
              <dt className="font-semibold">Database</dt>
              <dd className="m-0">{sample.db_reachable === false ? 'Unreachable' : 'Reachable'}</dd>
            </div>
            <div>
              <dt className="font-semibold">Service</dt>
              <dd className="m-0">{sample.service_running === false ? 'Stopped' : 'Running'}</dd>
            </div>
          </dl>
          <p className="m-0 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            Sampled {new Date(sample.sampled_at).toLocaleString()}
          </p>
        </>
      )}
    </section>
  )
}

export function SchemaBadge({ schema }: { schema: EgressSchemaCurrency | undefined }) {
  if (!schema) return null
  // Three honest states. A channel with no health sample yet has nothing to compare,
  // so it must NOT claim a confident green "Schema OK" alongside its other empty fields.
  if (schema.latest_sampled_at == null) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill label="No sample yet" tone="warn" />
        <span className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
          Schema currency is unknown until the channel produces a health sample.
        </span>
      </div>
    )
  }
  const churn = schema.proof_events_appended_since_last_sample ?? 0
  return (
    <div className="flex flex-wrap items-center gap-2">
      <StatusPill
        label={schema.is_current ? 'Schema OK' : 'Schema drift'}
        tone={schema.is_current ? 'ok' : 'err'}
      />
      <span
        // Drift guidance is load-bearing remediation text → larger + higher-contrast
        // than the steady-state "OK" line so an operator can act on it.
        className={schema.is_current ? 'text-[11px]' : 'text-xs'}
        style={{ color: schema.is_current ? 'var(--cc-ink-3)' : 'var(--cc-ink-2)' }}
      >
        {schema.is_current
          ? `Data schema v${schema.current_schema_version}`
          : `Last sample schema v${schema.sample_schema_version ?? '?'} ≠ running v${schema.current_schema_version} — update or re-migrate before relying on this data`}
        {' · '}
        {churn} proof event{churn === 1 ? '' : 's'} since last sample
      </span>
    </div>
  )
}

function formatMeasured(value: number | null | undefined, unit: string): string {
  return value == null ? 'Not measured yet' : `${value} ${unit}`
}

export function EgressReadinessPanel({
  channels,
  states,
  health,
  currency,
  loading,
  error,
  pendingCommand,
  canControl,
  onCommand,
}: {
  channels: ChannelProfile[]
  states: Map<string, EgressStateRow | null>
  health: Map<string, EgressHealthSample[]>
  currency: Map<string, EgressSchemaCurrency | undefined>
  loading: boolean
  error: unknown
  // The command currently being queued (only the pressed button shows
  // "Queuing...") — null when idle. Others stay disabled with their label.
  pendingCommand: { channelId: string; action: EgressCommandAction } | null
  canControl: boolean
  onCommand: (channelId: string, action: EgressCommandAction) => void
}) {
  const sending = pendingCommand !== null
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">Outgoing channel feed</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            This is the local CivicCast worker that sends each channel to its configured cable or streaming output.
          </p>
        </div>
        {loading && (
          <span className="cc-mono rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            checking
          </span>
        )}
      </div>
      {Boolean(error) && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Outgoing channel feed could not load.')}
        </div>
      )}
      {channels.length === 0 && !loading && (
        <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
          No channel profiles are configured yet.
        </div>
      )}
      <div className="grid gap-3 xl:grid-cols-2">
        {channels.map((channel) => {
          const state = states.get(channel.channel_id)
          const samples = health.get(channel.channel_id) ?? []
          const latestHealth = samples[0]
          const captionStatus = latestHealth?.caption_status ?? 'not-verified'
          const sinkEntries = latestHealth ? Object.entries(latestHealth.sink_connected) : []
          const schema = currency.get(channel.channel_id)
          const commandDisabled = sending || !canControl
          return (
            <article
              key={channel.channel_id}
              className="grid gap-3 rounded-md p-3"
              style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 className="m-0 text-sm font-semibold">{channel.branding.display_name}</h3>
                  <div className="cc-mono mt-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                    {channel.kind} / {channel.channel_id}
                  </div>
                </div>
                <StatusPill label={stateLabel(state?.state, 'Stopped')} tone={toneForEgressState(state?.state)} />
              </div>
              <dl className="m-0 grid gap-2 text-xs sm:grid-cols-2" style={{ color: 'var(--cc-ink-3)' }}>
                <div>
                  <dt className="font-semibold">Source</dt>
                  <dd className="m-0">{state?.current_source_label ?? 'None on air'}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Captions</dt>
                  <dd className="m-0">
                    {captionStatus === 'on'
                      ? 'On'
                      : 'Not yet confirmed (waiting for the on-air check)'}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">On air</dt>
                  <dd className="m-0">
                    {latestHealth ? humanizeDuration(latestHealth.seconds_on_air) : 'No sample yet'}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Encoder</dt>
                  <dd className="m-0">{formatMeasured(latestHealth?.encoder_fps, 'fps')}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Bitrate</dt>
                  <dd className="m-0">{formatMeasured(latestHealth?.encoder_bitrate_kbps, 'kbps')}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Dropped frames</dt>
                  <dd className="m-0">{latestHealth?.dropped_frames ?? 'No sample yet'}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Loudness</dt>
                  <dd className="m-0">
                    {latestHealth?.last_loudness_lufs != null ? `${latestHealth.last_loudness_lufs} LUFS` : 'No sample yet'}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Process</dt>
                  <dd className="m-0">{state?.pid ? `PID ${state.pid}` : 'Not running'}</dd>
                </div>
              </dl>
              {sinkEntries.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {sinkEntries.map(([sink, connected]) => (
                    <StatusPill key={sink} label={`${sink}: ${connected ? 'connected' : 'not connected'}`} tone={connected ? 'ok' : 'err'} />
                  ))}
                </div>
              )}
              <SchemaBadge schema={schema} />
              {state?.last_error && (
                <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
                  {state.last_error}
                </div>
              )}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {([
                  ['start', 'Start'],
                  ['stop', 'Stop'],
                  ['reload', 'Restart feed'],
                  ['drain', 'Finish current item, then stop'],
                ] as const).map(([action, label]) => {
                  const isThisSending =
                    pendingCommand?.channelId === channel.channel_id &&
                    pendingCommand?.action === action
                  return (
                    <button
                      key={action}
                      type="button"
                      disabled={commandDisabled}
                      onClick={() => onCommand(channel.channel_id, action)}
                      className="rounded-md px-3 py-2 text-sm font-semibold"
                      style={{
                        background: commandDisabled ? 'var(--cc-surface-3)' : 'var(--cc-ink)',
                        color: commandDisabled ? 'var(--cc-ink-3)' : 'var(--cc-ink-inv)',
                      }}
                    >
                      {isThisSending ? 'Queuing...' : label}
                    </button>
                  )
                })}
              </div>
              {!canControl && (
                <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  Outgoing feed controls require the meeting operator role.
                </p>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}

const GSTREAMER_REMEDY_LABEL: Record<GstreamerRepairResponse['remedy'], string> = {
  'already-healthy': 'GStreamer runtime is already healthy — nothing to repair.',
  'restage-launched': 'A signed re-stage of the GStreamer runtime was launched.',
  'installer-missing': 'Could not repair: the installer payload needed for the re-stage is missing.',
  'launch-failed': 'Could not repair: the re-stage launch failed.',
}

export function GstreamerRepairPanel({
  result,
  onRun,
  running,
  canRun,
  error,
}: {
  result?: GstreamerRepairResponse
  onRun: () => void
  running: boolean
  canRun: boolean
  error?: unknown
}) {
  const resultTone =
    result && (result.remedy === 'already-healthy' || result.closure_healthy)
      ? 'var(--cc-ok-soft)'
      : 'var(--cc-err-soft)'
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="m-0 text-base font-semibold">GStreamer engine repair</h2>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        If a corrupt GStreamer closure has degraded a channel onto the FFmpeg fallback engine,
        this re-verifies it in place and, if it&apos;s still broken, launches a signed re-stage.
        Never a reinstall.
      </p>
      {result && (
        <div className="grid gap-1 rounded-md p-3 text-xs" style={{ background: resultTone }}>
          <strong>{GSTREAMER_REMEDY_LABEL[result.remedy]}</strong>
          <span>{result.detail}</span>
          <span>
            Closure health right now: {result.closure_healthy ? 'healthy' : 'still degraded'}
            {result.pid != null ? ` · re-stage process PID ${result.pid}` : ''}
          </span>
        </div>
      )}
      {Boolean(error) && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'GStreamer repair could not run.')}
        </div>
      )}
      <button
        type="button"
        onClick={onRun}
        disabled={!canRun || running}
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: canRun ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRun ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {running ? 'Repairing…' : 'Repair GStreamer runtime & restore full egress'}
      </button>
      {!canRun && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Repairing the GStreamer runtime requires setup admin or support admin.
        </p>
      )}
    </section>
  )
}

export function RestorePanel({
  restore,
  realDrill,
  onRun,
  onRunReal,
  running,
  runningReal,
  canRun,
}: {
  restore?: RestoreStatus
  realDrill?: DrillReport
  onRun: () => void
  onRunReal: () => void
  running: boolean
  runningReal: boolean
  canRun: boolean
}) {
  const tone = toneForReadiness(restore?.status)
  const realRestorePassed =
    realDrill != null &&
    realDrill.restore.schema_ok &&
    (realDrill.restore.errors?.length ?? 0) === 0
  const crashRecoveryPassed =
    realDrill != null &&
    (realDrill.crash.results?.length ?? 0) > 0 &&
    (realDrill.crash.results ?? []).every((result) => result.ok)
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Backup and restore readiness</h2>
        {restore && <StatusPill label={readinessLabel(restore.status)} tone={tone} />}
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        {restore?.message ?? 'Checking restore status...'}
      </p>
      {restore?.proof_summary && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {restore.proof_summary}
        </p>
      )}
      {restore && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          <strong>Next step.</strong> {restore.next_step}
        </p>
      )}
      {restore && (restore.proof_items?.length ?? 0) > 0 && (
        <div className="grid gap-2">
          <h3 className="m-0 text-xs font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Restore proof checklist
          </h3>
          <ul className="m-0 grid gap-1 p-0 text-xs" style={{ listStyle: 'none' }}>
            {(restore.proof_items ?? []).map((item) => (
              <li
                key={item.id}
                className="grid gap-1 rounded-md p-2 sm:grid-cols-[1fr_auto]"
                style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
              >
                <span>
                  <strong style={{ color: 'var(--cc-ink)' }}>{item.label}</strong> - {item.message}
                </span>
                <StatusPill
                  label={stateLabel(item.state)}
                  tone={toneForReadiness(item.state)}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
      {restore && (restore.excluded_items?.length ?? 0) > 0 && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          <strong>Excluded.</strong> {(restore.excluded_items ?? []).join(', ')}.
        </p>
      )}
      {restore && (restore.plan_steps?.length ?? 0) > 0 && (
        <ol className="m-0 grid gap-1 pl-4 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {(restore.plan_steps ?? []).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      {realDrill && (
        <div className="grid gap-1 rounded-md p-3 text-xs" style={{ background: realRestorePassed && crashRecoveryPassed ? 'var(--cc-ok-soft)' : 'var(--cc-err-soft)' }}>
          <strong>{realRestorePassed && crashRecoveryPassed ? 'Real database restore drill passed' : 'Real database restore drill found a problem'}</strong>
          <span>
            Verified {realDrill.restore.tables?.length ?? 0} database tables in an isolated copy;
            crash recovery {crashRecoveryPassed ? 'passed' : 'did not pass'}.
          </span>
          <span>This proves the database path only; media, configuration, and credentials remain separate recovery work.</span>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onRun}
          disabled={!canRun || running || runningReal}
          className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: canRun ? 'var(--cc-surface-3)' : 'var(--cc-surface-3)', color: canRun ? 'var(--cc-ink)' : 'var(--cc-ink-3)' }}
        >
          {running ? 'Checking backup storage...' : 'Check backup storage'}
        </button>
        <button
          type="button"
          onClick={onRunReal}
          disabled={!canRun || running || runningReal}
          className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: canRun ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRun ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
        >
          {runningReal ? 'Restoring an isolated database copy...' : 'Run real database restore drill'}
        </button>
      </div>
      {!canRun && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Backup and restore checks require setup admin or support admin.
        </p>
      )}
    </section>
  )
}

function UpdateRollbackPanel({
  update,
  onRunPreflight,
  runningPreflight,
  canRunPreflight,
  onOpenMaintenanceWindow,
  openingMaintenanceWindow,
  onConfigureRollback,
  configuringRollback,
  onRunRollback,
  runningRollback,
  onRunFailedUpdateRollback,
  runningFailedUpdateRollback,
  onRunPostUpdateProof,
  runningPostUpdateProof,
  canManageRollback,
}: {
  update?: UpdateRollbackStatus
  onRunPreflight: () => void
  runningPreflight: boolean
  canRunPreflight: boolean
  onOpenMaintenanceWindow: () => void
  openingMaintenanceWindow: boolean
  onConfigureRollback: (artifactPath: string) => void
  configuringRollback: boolean
  onRunRollback: () => void
  runningRollback: boolean
  onRunFailedUpdateRollback: () => void
  runningFailedUpdateRollback: boolean
  onRunPostUpdateProof: () => void
  runningPostUpdateProof: boolean
  canManageRollback: boolean
}) {
  const [rollbackPath, setRollbackPath] = useState(update?.rollback_artifact ?? '')
  const tone = toneForReadiness(update?.status)
  const canUseButton = canRunPreflight && update?.status === 'update_available'
  const canOpenMaintenance =
    canRunPreflight &&
    update?.status === 'update_available' &&
    Boolean(update.last_preflight_at) &&
    update.rollback_proof_state === 'passed' &&
    !openingMaintenanceWindow
  const canSaveRollback = canManageRollback && rollbackPath.trim().length > 0 && !configuringRollback
  const canRunRollback = canManageRollback && Boolean(update?.rollback_available) && !runningRollback
  const canRunFailedUpdate =
    canManageRollback && update?.rollback_proof_state === 'passed' && !runningFailedUpdateRollback
  return (
    <section
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Update and rollback</h2>
        {update && <StatusPill label={stateLabel(update.status)} tone={tone} />}
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        {update?.message ?? 'Checking update status...'}
      </p>
      {update && (
        <dl className="m-0 grid gap-2 text-xs sm:grid-cols-2" style={{ color: 'var(--cc-ink-3)' }}>
          <div>
            <dt className="font-semibold">Current version</dt>
            <dd className="m-0 cc-mono">{update.current_version}</dd>
          </div>
          <div>
            <dt className="font-semibold">Rollback</dt>
            <dd className="m-0">{update.rollback_available ? 'Available' : 'Not configured'}</dd>
          </div>
          <div>
            <dt className="font-semibold">Rollback proof</dt>
            <dd className="m-0">{stateLabel(update.rollback_proof_state, 'Not set up yet')}</dd>
          </div>
          <div>
            <dt className="font-semibold">Failed-update proof</dt>
            <dd className="m-0">{stateLabel(update.failed_update_rollback_state, 'Not run')}</dd>
          </div>
          <div>
            <dt className="font-semibold">Post-update proof</dt>
            <dd className="m-0">{stateLabel(update.post_update_proof_state, 'Not run')}</dd>
          </div>
          <div>
            <dt className="font-semibold">Update preflight</dt>
            <dd className="m-0">{update.last_preflight_at ? 'Passed' : 'Required'}</dd>
          </div>
          <div>
            <dt className="font-semibold">Maintenance window</dt>
            <dd className="m-0">{stateLabel(update.maintenance_window_state, 'Closed')}</dd>
          </div>
          <div>
            <dt className="font-semibold">Last preflight</dt>
            <dd className="m-0">{update.last_preflight_at ? new Date(update.last_preflight_at).toLocaleString() : 'Not run'}</dd>
          </div>
          <div>
            <dt className="font-semibold">Window expires</dt>
            <dd className="m-0">{update.maintenance_window_expires_at ? new Date(update.maintenance_window_expires_at).toLocaleString() : 'Not open'}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="font-semibold">Migration safety</dt>
            <dd className="m-0">{update.migration_state}</dd>
          </div>
          {update.checkpoint_summary && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Checkpoint</dt>
              <dd className="m-0">{update.checkpoint_summary}</dd>
            </div>
          )}
          {update.rollback_artifact && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Rollback artifact</dt>
              <dd className="m-0 break-all cc-mono">{update.rollback_artifact}</dd>
            </div>
          )}
          {update.rollback_artifact_sha256 && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Rollback SHA-256</dt>
              <dd className="m-0 break-all cc-mono">{update.rollback_artifact_sha256}</dd>
            </div>
          )}
          {update.rollback_proof_summary && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Rollback proof summary</dt>
              <dd className="m-0">{update.rollback_proof_summary}</dd>
            </div>
          )}
          {update.maintenance_window_summary && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Maintenance summary</dt>
              <dd className="m-0">{update.maintenance_window_summary}</dd>
            </div>
          )}
          {update.failed_update_rollback_summary && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Failed-update proof summary</dt>
              <dd className="m-0">{update.failed_update_rollback_summary}</dd>
            </div>
          )}
          {update.post_update_proof_summary && (
            <div className="sm:col-span-2">
              <dt className="font-semibold">Post-update proof summary</dt>
              <dd className="m-0">{update.post_update_proof_summary}</dd>
            </div>
          )}
        </dl>
      )}
      {update && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          <strong>Next step.</strong> {update.next_step}
        </p>
      )}
      {update && (update.plan_steps?.length ?? 0) > 0 && (
        <ol className="m-0 grid gap-1 pl-4 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {(update.plan_steps ?? []).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      )}
      <button
        type="button"
        onClick={onRunPreflight}
        disabled={!canUseButton || runningPreflight}
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: canUseButton ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canUseButton ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {runningPreflight ? 'Running update preflight...' : update?.safe_to_apply ? 'Rerun update preflight' : 'Run update preflight'}
      </button>
      <button
        type="button"
        onClick={onOpenMaintenanceWindow}
        disabled={!canOpenMaintenance}
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: canOpenMaintenance ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canOpenMaintenance ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {openingMaintenanceWindow ? 'Opening maintenance window...' : 'Open maintenance window'}
      </button>
      {!canRunPreflight && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Update preflight requires setup admin or support admin.
        </p>
      )}
      <div className="grid gap-2">
        <label className="grid gap-1 text-xs" htmlFor="rollback-artifact-path">
          <span className="font-semibold">Rollback artifact path</span>
          <input
            id="rollback-artifact-path"
            value={rollbackPath}
            onChange={(event) => setRollbackPath(event.target.value)}
            disabled={!canManageRollback}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            placeholder="Example: C:\\CivicCast\\releases\\CivicCast_1.4.0_x64-setup.exe"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onConfigureRollback(rollbackPath.trim())}
            disabled={!canSaveRollback}
            className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: canSaveRollback ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canSaveRollback ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
          >
            {configuringRollback ? 'Saving rollback artifact...' : 'Save rollback artifact'}
          </button>
          <button
            type="button"
            onClick={onRunRollback}
            disabled={!canRunRollback}
            className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: canRunRollback ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRunRollback ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
          >
            {runningRollback ? 'Running rollback rehearsal...' : 'Run rollback rehearsal'}
          </button>
          <button
            type="button"
            onClick={onRunFailedUpdateRollback}
            disabled={!canRunFailedUpdate}
            className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: canRunFailedUpdate ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRunFailedUpdate ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
          >
            {runningFailedUpdateRollback ? 'Running failed-update rehearsal...' : 'Run failed-update rehearsal'}
          </button>
          <button
            type="button"
            onClick={onRunPostUpdateProof}
            disabled={!canManageRollback || runningPostUpdateProof}
            className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: canManageRollback ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canManageRollback ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
          >
            {runningPostUpdateProof ? 'Running post-update proof...' : 'Run post-update proof'}
          </button>
        </div>
        {!canManageRollback && (
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Rollback setup requires setup admin or support admin.
          </p>
        )}
      </div>
    </section>
  )
}

export function SupportBundlePanel({ canCreate }: { canCreate: boolean }) {
  const [note, setNote] = useState('')
  const bundle = useMutation<DiagnosticBundleResponse, Error>({
    mutationFn: () => createSupportBundle({ operator_note: note.trim() === '' ? null : note }),
  })
  const download = useMutation<Blob, Error, string>({
    mutationFn: (bundleId) => downloadSupportBundle(bundleId),
    onSuccess: (blob, bundleId) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${bundleId}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    },
  })

  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <h2 className="m-0 text-base font-semibold">Support bundle</h2>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Generate a redacted troubleshooting file for tester support.
        </p>
      </div>
      <label className="grid gap-1 text-sm" htmlFor="support-note">
        <span className="font-semibold">Short note</span>
        <textarea
          id="support-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          disabled={!canCreate}
          className="min-h-20 rounded-md px-3 py-2"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          placeholder="Example: rehearsal failed after the camera was unplugged."
        />
      </label>
      <button
        type="button"
        disabled={!canCreate || bundle.isPending}
        onClick={() => bundle.mutate()}
        className="w-fit rounded-md px-4 py-2 text-sm font-semibold"
        style={{ background: canCreate ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canCreate ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {bundle.isPending ? 'Creating bundle...' : 'Create support bundle'}
      </button>
      {!canCreate && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Support bundles require support admin.
        </p>
      )}
      {bundle.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(bundle.error, 'Support bundle failed.')}
        </div>
      )}
      {bundle.data && (
        <div className="grid gap-1 rounded-md p-3 text-xs" style={{ background: 'var(--cc-ok-soft)' }}>
          <div className="font-semibold">Support bundle ready</div>
          <button
            type="button"
            disabled={download.isPending}
            onClick={() => download.mutate(bundle.data.bundle_id)}
            className="my-2 w-fit rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
          >
            {download.isPending ? 'Downloading support bundle...' : 'Download support bundle'}
          </button>
          {download.error && (
            <div role="alert" style={{ color: 'var(--cc-err)' }}>
              {apiMessage(download.error, 'Support bundle download failed.')}
            </div>
          )}
          <div className="cc-mono break-all">{bundle.data.path}</div>
          <div className="cc-mono break-all" style={{ color: 'var(--cc-ink-3)' }}>
            SHA-256 {bundle.data.sha256}
          </div>
          <div style={{ color: 'var(--cc-ink-3)' }}>{bundle.data.next_step}</div>
        </div>
      )}
    </section>
  )
}

export function SystemHealthScreen() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    retry: false,
  })
  const egressStatusQuery = useQuery({
    queryKey: ['system-health-egress', channelsQuery.data?.map((channel) => channel.channel_id).join(',') ?? 'none'],
    queryFn: async () => {
      const channels = channelsQuery.data ?? []
      const rows = await Promise.all(
        channels.map(async (channel) => {
          const [state, health] = await Promise.all([
            getEgressState(channel.channel_id),
            getEgressHealth(channel.channel_id),
          ])
          // Schema currency is an advisory badge, not a critical readiness signal:
          // a failure here must not blank out the whole outgoing-feed panel.
          const currency = await getEgressSchemaCurrency(channel.channel_id).catch(() => undefined)
          return [channel.channel_id, state, health, currency] as const
        }),
      )
      return {
        states: new Map(rows.map(([channelId, state]) => [channelId, state])),
        health: new Map(rows.map(([channelId, , health]) => [channelId, health])),
        currency: new Map(rows.map(([channelId, , , currency]) => [channelId, currency])),
      }
    },
    enabled: (channelsQuery.data?.length ?? 0) > 0,
    retry: false,
  })
  const restoreQuery = useQuery({
    queryKey: ['restore-status'],
    queryFn: getRestoreStatus,
    retry: false,
  })
  const updateQuery = useQuery({
    queryKey: ['update-rollback-status'],
    queryFn: getUpdateRollbackStatus,
    retry: false,
  })
  const healthQuery = useQuery({
    queryKey: ['system-health'],
    queryFn: getSystemHealth,
    retry: false,
  })
  // The live "are we on air right now" signal. Server caches it ~4s, so a 5s
  // poll keeps the banner fresh without stampeding the egress store.
  const runtimeQuery = useQuery({
    queryKey: ['runtime-safe-to-air'],
    queryFn: getRuntimeSafeToAir,
    retry: false,
    refetchInterval: 5000,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const rehearsal = useMutation({
    mutationFn: startFirstBroadcastRehearsal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const restoreRehearsal = useMutation({
    mutationFn: runRestoreRehearsal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['restore-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const disasterRecoveryDrill = useMutation({
    mutationFn: runDisasterRecoveryDrill,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['restore-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const updatePreflight = useMutation({
    mutationFn: runUpdatePreflight,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const maintenanceWindow = useMutation({
    mutationFn: () => openUpdateMaintenanceWindow(60),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const rollbackArtifact = useMutation({
    mutationFn: (artifactPath: string) => configureRollbackArtifact({ artifact_path: artifactPath }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const rollbackRehearsal = useMutation({
    mutationFn: runRollbackRehearsal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const failedUpdateRollback = useMutation({
    mutationFn: runFailedUpdateRollbackRehearsal,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const postUpdateProof = useMutation({
    mutationFn: runPostUpdateProof,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-rollback-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const egressCommandMutation = useMutation({
    mutationFn: ({ channelId, action }: { channelId: string; action: EgressCommandAction }) =>
      queueEgressCommand(channelId, action),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['system-health-egress'] })
      void queryClient.invalidateQueries({ queryKey: ['egress-state', variables.channelId] })
      void queryClient.invalidateQueries({ queryKey: ['egress-health', variables.channelId] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const gstreamerRepair = useMutation({
    mutationFn: repairGstreamerRuntime,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['system-health-egress'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const selfTestRun = useMutation({
    mutationFn: () => runSelfTestNow('daily'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      void queryClient.invalidateQueries({ queryKey: ['self-tests'] })
    },
  })
  const selfTestRunWeekly = useMutation({
    mutationFn: () => runSelfTestNow('weekly'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      void queryClient.invalidateQueries({ queryKey: ['self-tests'] })
    },
  })

  const report = healthQuery.data
  const canRunMeetingRehearsal =
    !staffIdentityQuery.isSuccess || hasOperatorRole(staffIdentityQuery.data, 'meeting_operator')
  const canRunRestoreRehearsal =
    !staffIdentityQuery.isSuccess ||
    hasOperatorRole(staffIdentityQuery.data, 'setup_admin') ||
    hasOperatorRole(staffIdentityQuery.data, 'support_admin')
  const canRunUpdatePreflight = canRunRestoreRehearsal
  const canCreateSupportBundle =
    !staffIdentityQuery.isSuccess || hasOperatorRole(staffIdentityQuery.data, 'support_admin')
  const latestUpdateStatus =
    postUpdateProof.data ??
    failedUpdateRollback.data ??
    maintenanceWindow.data ??
    rollbackRehearsal.data ??
    rollbackArtifact.data ??
    updatePreflight.data ??
    updateQuery.data
  const requiredChecks = report?.checks.filter((check) => check.required) ?? []
  const optionalChecks = report?.checks.filter((check) => !check.required) ?? []

  return (
    <div className="grid gap-5 px-6 py-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
            System Health
          </div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">Safe to broadcast</h1>
          <p className="m-0 mt-1 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            One place to see whether the station is ready, what needs setup, and what residents can see.
          </p>
        </div>
        {report && <HealthPill color={report.safe_to_broadcast} />}
      </header>

      <RuntimeSafeToAirBanner status={runtimeQuery.data} onOpenAlerts={() => navigate('/alerts')} />
      {runtimeQuery.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(runtimeQuery.error, 'The live on-air signal could not load.')}
        </div>
      )}

      {healthQuery.isLoading && (
        <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Checking station readiness...
        </div>
      )}

      {healthQuery.error && (
        <div role="alert" className="rounded-md p-4" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          <div className="text-sm font-semibold">Could not load System Health.</div>
          <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            {apiMessage(healthQuery.error, 'Check setup and staff-token state.')}
          </div>
        </div>
      )}

      {report && (
        <>
          <section
            className="grid gap-4 rounded-md p-4 lg:grid-cols-[1fr_280px]"
            style={{ background: COLOR_TONE[report.safe_to_broadcast].bg, border: `1px solid ${COLOR_TONE[report.safe_to_broadcast].border}` }}
          >
            <div>
              <h2 className="m-0 text-lg font-semibold">{report.label}</h2>
              <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
                {report.operator_message}
              </p>
              <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Last checked {new Date(report.generated_at).toLocaleString()}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <a
                href={report.resident_preview.public_url}
                target="_blank"
                rel="noreferrer"
                className="rounded-md px-3 py-2 font-semibold no-underline"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
              >
                Open resident preview
              </a>
              <button
                type="button"
                onClick={() => rehearsal.mutate()}
                disabled={!canRunMeetingRehearsal || rehearsal.isPending}
                className="rounded-md px-3 py-2 font-semibold"
                style={{ background: canRunMeetingRehearsal ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: canRunMeetingRehearsal ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
              >
                Check broadcast readiness
              </button>
            </div>
          </section>

          {staffIdentityQuery.isSuccess && !canRunMeetingRehearsal && (
            <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
              Checking broadcast readiness requires the meeting operator role. Health checks remain visible.
            </div>
          )}

          {rehearsal.data && <RehearsalPanel report={rehearsal.data} />}
          {rehearsal.error && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(rehearsal.error, 'The broadcast readiness check failed.')}
            </div>
          )}

          <EgressReadinessPanel
            channels={channelsQuery.data ?? []}
            states={egressStatusQuery.data?.states ?? new Map()}
            health={egressStatusQuery.data?.health ?? new Map()}
            currency={egressStatusQuery.data?.currency ?? new Map()}
            loading={channelsQuery.isLoading || egressStatusQuery.isLoading}
            error={channelsQuery.error ?? egressStatusQuery.error ?? egressCommandMutation.error}
            pendingCommand={egressCommandMutation.isPending ? (egressCommandMutation.variables ?? null) : null}
            canControl={canRunMeetingRehearsal}
            onCommand={(channelId, action) => egressCommandMutation.mutate({ channelId, action })}
          />

          <GstreamerRepairPanel
            result={gstreamerRepair.data}
            onRun={() => {
              if (
                window.confirm(
                  'Repair the GStreamer runtime? If the closure is still broken this launches a signed re-stage of the native egress engine.',
                )
              ) {
                gstreamerRepair.mutate()
              }
            }}
            running={gstreamerRepair.isPending}
            canRun={canRunRestoreRehearsal}
            error={gstreamerRepair.error}
          />

          <section className="grid gap-3 lg:grid-cols-3">
            <RestorePanel
              restore={restoreRehearsal.data ?? restoreQuery.data}
              realDrill={disasterRecoveryDrill.data}
              onRun={() => restoreRehearsal.mutate()}
              onRunReal={() => disasterRecoveryDrill.mutate()}
              running={restoreRehearsal.isPending}
              runningReal={disasterRecoveryDrill.isPending}
              canRun={canRunRestoreRehearsal}
            />
            <UpdateRollbackPanel
              update={latestUpdateStatus}
              onRunPreflight={() => updatePreflight.mutate()}
              runningPreflight={updatePreflight.isPending}
              canRunPreflight={canRunUpdatePreflight}
              onOpenMaintenanceWindow={() => maintenanceWindow.mutate()}
              openingMaintenanceWindow={maintenanceWindow.isPending}
              onConfigureRollback={(artifactPath) => rollbackArtifact.mutate(artifactPath)}
              configuringRollback={rollbackArtifact.isPending}
              onRunRollback={() => rollbackRehearsal.mutate()}
              runningRollback={rollbackRehearsal.isPending}
              onRunFailedUpdateRollback={() => failedUpdateRollback.mutate()}
              runningFailedUpdateRollback={failedUpdateRollback.isPending}
              onRunPostUpdateProof={() => postUpdateProof.mutate()}
              runningPostUpdateProof={postUpdateProof.isPending}
              canManageRollback={canRunUpdatePreflight}
            />
            <SupportBundlePanel canCreate={canCreateSupportBundle} />
          </section>

          {(restoreQuery.error || restoreRehearsal.error || disasterRecoveryDrill.error || updateQuery.error || updatePreflight.error || maintenanceWindow.error || rollbackArtifact.error || rollbackRehearsal.error || failedUpdateRollback.error || postUpdateProof.error) && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(restoreQuery.error ?? restoreRehearsal.error ?? disasterRecoveryDrill.error ?? updateQuery.error ?? updatePreflight.error ?? maintenanceWindow.error ?? rollbackArtifact.error ?? rollbackRehearsal.error ?? failedUpdateRollback.error ?? postUpdateProof.error, 'Advanced health status could not load.')}
            </div>
          )}

          <section className="grid gap-3 lg:grid-cols-2">
            <SelfTestPanel
              selfTest={selfTestRunWeekly.data ?? selfTestRun.data ?? report.last_self_test}
              onRun={() => selfTestRun.mutate()}
              running={selfTestRun.isPending}
              onRunWeekly={() => selfTestRunWeekly.mutate()}
              runningWeekly={selfTestRunWeekly.isPending}
              canRun={canRunRestoreRehearsal}
              error={selfTestRun.error ?? selfTestRunWeekly.error}
            />
            <ResourceSnapshotPanel sample={report.latest_resource_sample} />
          </section>

          <section className="grid gap-3">
            <h2 className="m-0 text-base font-semibold">Required before broadcast</h2>
            <div className="grid gap-2">
              {requiredChecks.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </div>
          </section>

          <section className="grid gap-3">
            <h2 className="m-0 text-base font-semibold">Optional and advanced</h2>
            <div className="grid gap-2">
              {optionalChecks.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
