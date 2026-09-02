import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  ApiError,
  createLiveSession,
  endLiveBroadcast,
  evaluateLivePreflight,
  getLiveIngestPlan,
  getStaffIdentity,
  getLiveFinalizationStatus,
  getLiveSession,
  getLiveSourceById,
  getSafeToBroadcast,
  getSourceSetup,
  goLiveOnAir,
  listChannelProfiles,
  listLiveSources,
  listRecordingTargets,
  probeLiveSource,
  updateLiveSource,
  retryLiveFinalization,
  startLivePreflight,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { ConfirmDialog, type PendingConfirm } from '../components/ConfirmDialog'
import { RadioCardGroup } from '../components/RadioCardGroup'
import {
  READINESS_DO_NOT_BROADCAST_YET,
  readinessLabel,
  toneForReadiness,
} from './status-language'
import {
  LIVE_STATE_META,
  PREFLIGHT_LABELS,
  preflightNextStep,
  observationAgeLabel,
  RELAY_HEALTH_LABEL,
  RELAY_MODE_LABEL,
  SOURCE_READINESS_LABEL,
  SOURCE_READINESS_TONE,
  SOURCE_TYPE_LABEL,
  type LiveIngestHealth,
  type LiveIngestPath,
  type LiveIngestPlan,
  type LiveSessionResponse,
  type LiveSourceResponse,
  type LiveSourceType,
  type LiveSourceUpdate,
  type PreflightEvaluation,
  type PreflightInputs,
} from '../types/live'
import type {
  LiveFinalizationStatusResponse,
  SourceSetupReport,
  SystemHealthReport,
} from '../types/api.generated'

// Stage G: the live-room channel is operator-selected (persisted locally);
// this is only the fallback when no choice is stored and the channel list
// has not loaded yet.
const DEFAULT_CHANNEL_ID = 'government'
const CHANNEL_STORAGE_KEY = 'civiccast.liveRoom.channelId'
const SESSION_ID = 'council-live-room'
const SESSION_TITLE = 'Council live room'
const EMPTY_SOURCES: LiveSourceResponse[] = []

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function StatusPill({
  label,
  tone,
}: {
  label: string
  tone: 'neutral' | 'info' | 'ok' | 'warn' | 'live' | 'err'
}) {
  const palette = {
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
    info: { bg: '#e2f0fa', fg: '#12384f' },
    ok: { bg: '#e4f6ea', fg: '#0f5132' },
    warn: { bg: '#fff0c7', fg: '#533b03' },
    live: { bg: '#fee7e3', fg: '#6f1515' },
    err: { bg: '#fde6e8', fg: '#72131d' },
  }[tone]
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {label}
    </span>
  )
}

function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
    >
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {message}
      </div>
      <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong> Confirm the CivicCast server is running and
        connected to its database, then refresh this screen.
      </div>
    </div>
  )
}

export function SafeToBroadcastPanel({
  report,
  isLoading,
  error,
  onRetry,
}: {
  report: SystemHealthReport | undefined
  isLoading: boolean
  error: Error | null
  onRetry: () => void
}) {
  const palette = {
    green: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)', label: 'Ready' },
    // Matches docs/operator-language-guide.md and the installer's readiness
    // label; keep these three in step if any of them changes.
    yellow: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)', label: 'Check before meeting' },
    red: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)', label: 'Do not broadcast yet' },
  } as const
  if (error) {
    return (
      <section
        role="alert"
        className="rounded-md p-4 text-sm"
        style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
      >
        <div className="font-semibold">Broadcast readiness could not be checked. Do not start the stream.</div>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Retry the check. If it fails again, open System Health and confirm the
          CivicCast service and database are ready.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md px-3 py-2 text-xs font-semibold"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          Retry check
        </button>
      </section>
    )
  }
  if (isLoading || !report) {
    return (
      <section className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
        Checking safe-to-broadcast state...
      </section>
    )
  }
  const tone = palette[report.safe_to_broadcast]
  return (
    <section
      className="grid gap-3 rounded-md p-4 md:grid-cols-[1fr_auto]"
      style={{ background: tone.bg, border: `1px solid ${tone.fg}`, color: 'var(--cc-ink)' }}
    >
      <div>
        <h2 className="m-0 text-sm font-semibold">Safe to broadcast: {tone.label}</h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {report.operator_message}
        </p>
      </div>
      <a
        href={report.resident_preview.public_url}
        target="_blank"
        rel="noreferrer"
        className="rounded-md px-3 py-2 text-center text-xs font-semibold no-underline"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      >
        Resident preview
      </a>
    </section>
  )
}

function FinalizationPanel({
  session,
  onSessionRefresh,
}: {
  session: LiveSessionResponse
  onSessionRefresh: (next: LiveSessionResponse) => void
}) {
  const active = session.state === 'ending' || session.state === 'recorded'
  const statusQuery = useQuery<LiveFinalizationStatusResponse, Error>({
    queryKey: ['live-finalization', session.live_session_id],
    queryFn: () => getLiveFinalizationStatus(session.live_session_id),
    enabled: active,
    retry: false,
    // 404 is expected for up to one worker poll interval after End; keep
    // polling until the job reaches a terminal state.
    refetchInterval: (query) => (query.state.data?.terminal ? false : 3000),
  })
  const sessionQuery = useQuery<LiveSessionResponse, Error>({
    queryKey: ['live-session-refresh', session.live_session_id],
    queryFn: () => getLiveSession(session.live_session_id),
    enabled: session.state === 'ending',
    retry: false,
    refetchInterval: 3000,
  })
  const refreshed = sessionQuery.data
  useEffect(() => {
    if (refreshed && refreshed.state !== session.state) {
      onSessionRefresh(refreshed)
    }
  }, [refreshed, session.state, onSessionRefresh])
  const retryMutation = useMutation({
    mutationFn: () => retryLiveFinalization(session.live_session_id),
    onSuccess: () => statusQuery.refetch(),
  })
  if (!active) return null
  const job = statusQuery.data
  const tone = !job
    ? 'warn'
    : job.state === 'completed'
      ? 'ok'
      : job.state === 'failed'
        ? job.terminal
          ? 'err'
          : 'warn'
        : 'info'
  return (
    <section
      aria-label="Recording finalization"
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 text-sm font-semibold">Recording finalization</h2>
        <StatusPill
          label={
            !job
              ? 'Waiting'
              : job.state === 'failed' && !job.terminal
                ? 'Retrying'
                : job.state.charAt(0).toUpperCase() + job.state.slice(1)
          }
          tone={tone as 'neutral' | 'info' | 'ok' | 'warn' | 'live' | 'err'}
        />
      </div>
      {!job && (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          The finalization worker picks the recording up within a few seconds
          of End Live Stream. This panel updates automatically.
        </p>
      )}
      {job?.state === 'completed' && (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Recording saved{job.asset_id ? ` as asset ${job.asset_id}` : ''}. Find
          it in the Assets library.
        </p>
      )}
      {job?.state === 'failed' && (
        <div className="mt-2 flex flex-col gap-2">
          <p className="m-0 text-xs" role="alert" style={{ color: 'var(--cc-err)' }}>
            {job.failure_reason ?? 'Finalization failed.'}
          </p>
          {job.terminal && (
            <button
              type="button"
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="self-start rounded-md px-3 py-2 text-xs font-semibold"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              Retry finalization
            </button>
          )}
        </div>
      )}
      {job && job.state !== 'completed' && job.state !== 'failed' && (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Attempt {job.attempts} of {job.max_attempts}. The recording is being
          checked and packaged.
        </p>
      )}
    </section>
  )
}

export function SourceSwitcher({
  sources,
  selectedId,
  onSelect,
  onCheck,
  onEdit,
  checkingId,
  canEdit,
  canCheck,
}: {
  sources: LiveSourceResponse[]
  selectedId: string
  onSelect: (id: string) => void
  onCheck?: (id: string) => void
  onEdit?: (source: LiveSourceResponse) => void
  checkingId?: string | null
  canEdit?: boolean
  canCheck?: boolean
}) {
  const selected = sources.find((source) => source.live_source_id === selectedId)
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="m-0 text-sm font-semibold">Source switcher</h2>
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Arrow keys move between configured meeting sources. A source is only
          shown as delivering if CivicCast has actually seen media from it in
          the last {selected?.readiness_ttl_seconds ?? 30} seconds.
        </p>
      </div>
      <RadioCardGroup
        label="Live source"
        options={sources.map((source) => ({
          id: source.live_source_id,
          label: source.name,
          trailing: (
            <span className="flex items-center gap-1">
              <StatusPill
                label={SOURCE_READINESS_LABEL[source.readiness]}
                tone={SOURCE_READINESS_TONE[source.readiness]}
              />
              <StatusPill
                label={SOURCE_TYPE_LABEL[source.source_type]}
                tone="neutral"
              />
            </span>
          ),
          description: (
            <span className="block">
              <span
                className="cc-mono block truncate"
                style={{ color: 'var(--cc-ink-3)' }}
              >
                {source.endpoint_url}
              </span>
              <span className="mt-1 block" style={{ color: 'var(--cc-ink-3)' }}>
                {observationAgeLabel(source.observation_age_seconds)}
              </span>
            </span>
          ),
        }))}
        value={selectedId}
        onChange={onSelect}
        className="grid gap-2 md:grid-cols-2"
        buttonClassName="min-h-24 rounded-md p-3 text-left"
        getDescriptionColor={() => 'var(--cc-ink-3)'}
      />
      {selected ? (
        <SourceReadinessDetail
          source={selected}
          onCheck={onCheck}
          onEdit={onEdit}
          checking={checkingId === selected.live_source_id}
          canEdit={canEdit}
          canCheck={canCheck}
        />
      ) : null}
    </section>
  )
}

/**
 * What the operator needs about the selected source, in the order they need
 * it: what was seen, when, why not (if not), and the one thing to do next.
 *
 * The "Check source" button exists because before WP-07 there was no way to
 * ask -- readiness was asserted by the existence of the row, so there was
 * nothing to re-ask.
 */
export function SourceReadinessDetail({
  source,
  onCheck,
  onEdit,
  checking,
  canEdit,
  canCheck,
}: {
  source: LiveSourceResponse
  onCheck?: (id: string) => void
  onEdit?: (source: LiveSourceResponse) => void
  checking?: boolean
  canEdit?: boolean
  canCheck?: boolean
}) {
  const tone = SOURCE_READINESS_TONE[source.readiness]
  const background =
    tone === 'ok'
      ? 'var(--cc-surface)'
      : tone === 'err'
        ? 'var(--cc-err-soft)'
        : tone === 'warn'
          ? 'var(--cc-warn-soft)'
          : 'var(--cc-surface-2)'
  return (
    <section
      className="rounded-md p-4"
      style={{ background, border: '1px solid var(--cc-line)' }}
      aria-label={`Readiness for ${source.name}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="m-0 text-sm font-semibold">{source.name}</h3>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            {observationAgeLabel(source.observation_age_seconds)}
          </p>
        </div>
        <StatusPill label={SOURCE_READINESS_LABEL[source.readiness]} tone={tone} />
      </div>
      {source.readiness === 'failed' && source.probe_detail ? (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {source.probe_detail}
        </p>
      ) : null}
      <p className="m-0 mt-2 text-xs font-semibold" style={{ color: 'var(--cc-ink-2)' }}>
        Next step: {source.next_action}
      </p>
      {!source.credentials_supported && source.credentials_unsupported_reason ? (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {source.credentials_unsupported_reason}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {onCheck && canCheck ? (
          <button
            type="button"
            onClick={() => onCheck(source.live_source_id)}
            disabled={checking}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{
              background: 'var(--cc-surface-3)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
              opacity: checking ? 0.6 : 1,
            }}
          >
            {checking ? 'Checking source...' : 'Check source'}
          </button>
        ) : null}
        {onEdit && canEdit ? (
          <button
            type="button"
            onClick={() => onEdit(source)}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{
              background: 'transparent',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink-2)',
            }}
          >
            Edit source
          </button>
        ) : null}
      </div>
      {onEdit && !canEdit ? (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Editing a source needs the setup admin role. Ask your station admin to
          change the address or type.
        </p>
      ) : null}
      {onCheck && !canCheck ? (
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Checking a source needs the meeting operator or setup admin role. Ask
          a meeting operator or your station admin to confirm it is delivering
          media.
        </p>
      ) : null}
    </section>
  )
}

/**
 * Rename or re-point a configured source.
 *
 * Deliberately warns before saving anything that changes what would be
 * probed: the server clears readiness on those edits, so the operator loses
 * their "delivering" state and has to check again. Saying so up front is the
 * difference between an informed edit and a surprise at gavel time.
 *
 * `conflict` is the row a 409 revealed the server actually holds now (WP-07
 * hostile-review finding N2). It is display-only: the fields below keep
 * whatever the operator already typed (that is the whole point -- a 409
 * must not silently discard work in progress) and `conflict`'s values are
 * shown alongside the ones that actually differ, so the operator can see
 * what changed and decide what to do, rather than either losing their edit
 * or blindly overwriting someone else's.
 */
export function SourceEditForm({
  source,
  conflict,
  onCancel,
  onSave,
  saving,
  error,
}: {
  source: LiveSourceResponse
  conflict?: LiveSourceResponse | null
  onCancel: () => void
  onSave: (payload: LiveSourceUpdate) => void
  saving?: boolean
  error?: string | null
}) {
  const [name, setName] = useState(source.name)
  const [endpoint, setEndpoint] = useState(source.endpoint_url)
  const [sourceType, setSourceType] = useState<LiveSourceType>(source.source_type)
  const [credentialsHandle, setCredentialsHandle] = useState(
    source.credentials_handle ?? '',
  )

  const endpointChanged = endpoint.trim() !== source.endpoint_url
  const typeChanged = sourceType !== source.source_type
  const credentialChanged =
    credentialsHandle.trim() !== (source.credentials_handle ?? '')
  const invalidatesReadiness = endpointChanged || typeChanged || credentialChanged
  const credentialsSupported = sourceType === 'srt'

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const payload: LiveSourceUpdate = { expected_row_version: source.row_version }
    if (name.trim() !== source.name) payload.name = name.trim()
    if (endpointChanged) payload.endpoint_url = endpoint.trim()
    if (typeChanged) payload.source_type = sourceType
    if (credentialChanged) {
      if (credentialsHandle.trim()) payload.credentials_handle = credentialsHandle.trim()
      else payload.clear_credentials_handle = true
    }
    onSave(payload)
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      aria-label={`Edit ${source.name}`}
    >
      <h3 className="m-0 text-sm font-semibold">Edit meeting source</h3>
      <div className="mt-3 flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="source-edit-name" className="text-xs font-semibold">
            Name
          </label>
          <input
            id="source-edit-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="rounded-md px-2 py-2 text-sm"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          />
          {conflict && conflict.name !== source.name ? (
            <p className="m-0 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
              Server now has: {conflict.name}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="source-edit-type" className="text-xs font-semibold">
            Source type
          </label>
          <select
            id="source-edit-type"
            value={sourceType}
            onChange={(event) => {
              const nextType = event.target.value as LiveSourceType
              setSourceType(nextType)
              // The credential field is only visually blanked while a
              // non-SRT type is disabled-and-shown-empty (below); the state
              // itself used to survive the switch and get re-submitted if
              // the operator switched back to SRT without retyping it. Clear
              // it here so the state and the display never disagree.
              if (nextType !== 'srt') setCredentialsHandle('')
            }}
            className="rounded-md px-2 py-2 text-sm"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
          >
            {(['rtmp', 'rtsp', 'ndi', 'srt'] as LiveSourceType[]).map((value) => (
              <option key={value} value={value}>
                {SOURCE_TYPE_LABEL[value]}
              </option>
            ))}
          </select>
          {conflict && conflict.source_type !== source.source_type ? (
            <p className="m-0 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
              Server now has: {SOURCE_TYPE_LABEL[conflict.source_type]}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="source-edit-endpoint" className="text-xs font-semibold">
            {sourceType === 'ndi' ? 'NDI source name' : 'Stream address'}
          </label>
          <input
            id="source-edit-endpoint"
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
            className="cc-mono rounded-md px-2 py-2 text-sm"
            style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
            aria-describedby="source-edit-endpoint-help"
          />
          <p
            id="source-edit-endpoint-help"
            className="m-0 text-xs"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            {sourceType === 'ndi'
              ? 'The NDI source name exactly as the sender advertises it on the station network.'
              : 'Do not include a username or password. CivicCast will not store a password inside an address.'}
          </p>
          {conflict && conflict.endpoint_url !== source.endpoint_url ? (
            <p className="cc-mono m-0 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
              Server now has: {conflict.endpoint_url}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="source-edit-credential" className="text-xs font-semibold">
            Stored credential
          </label>
          <input
            id="source-edit-credential"
            value={credentialsSupported ? credentialsHandle : ''}
            onChange={(event) => setCredentialsHandle(event.target.value)}
            disabled={!credentialsSupported}
            className="rounded-md px-2 py-2 text-sm"
            style={{
              background: 'var(--cc-surface-2)',
              border: '1px solid var(--cc-line)',
              opacity: credentialsSupported ? 1 : 0.5,
            }}
            aria-describedby="source-edit-credential-help"
          />
          <p
            id="source-edit-credential-help"
            className="m-0 text-xs"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            {credentialsSupported
              ? 'The name the SRT passphrase for this source is saved under in the station credential store. The passphrase itself is never stored here.'
              : source.credentials_unsupported_reason ??
                'This source type cannot use a stored credential.'}
          </p>
          {conflict && conflict.credentials_handle !== source.credentials_handle ? (
            <p className="m-0 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
              Server now has: {conflict.credentials_handle || '(no stored credential)'}
            </p>
          ) : null}
        </div>
      </div>
      {conflict ? (
        <p
          className="m-0 mt-3 rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink-2)' }}
          role="status"
        >
          Someone else saved a change to this source first. Your typed changes
          above were kept -- compare them with the "Server now has" lines and
          save again when you're ready; saving will overwrite the server's
          current values with what's shown above.
        </p>
      ) : null}
      {invalidatesReadiness ? (
        <p
          className="m-0 mt-3 rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink-2)' }}
          role="status"
        >
          Saving this change clears what CivicCast knows about this source. You
          will need to choose Check source again before it can take air.
        </p>
      ) : null}
      {error ? (
        <p className="m-0 mt-3 text-xs" role="alert" style={{ color: 'var(--cc-err)' }}>
          {error}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: 'var(--cc-accent)',
            color: 'var(--cc-accent-ink)',
            opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? 'Saving...' : 'Save source'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'transparent', border: '1px solid var(--cc-line)' }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

function RelayStatusPanel({
  plan,
  error,
}: {
  plan: LiveIngestPlan | undefined
  error: unknown
}) {
  const toneFor = (state: LiveIngestHealth) => {
    if (state === 'ready') return 'ok'
    if (state === 'degraded' || state === 'not_configured') return 'warn'
    return 'err'
  }
  const pathDescription = (path: LiveIngestPath) => {
    if (path.outbound_only) return 'Outbound only; no inbound firewall opening is required.'
    if (path.requires_inbound_firewall) return 'Requires an inbound route from the encoder.'
    if (!path.enabled) return 'Not usable -- add a real source below instead.'
    return 'Configured meeting source.'
  }
  if (error) {
    return (
      <section className="rounded-md p-4" style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}>
        <h2 className="m-0 text-sm font-semibold">Remote ingest</h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Remote ingest status is unavailable. Local encoder sources can still run from this room.
        </p>
      </section>
    )
  }
  if (!plan) {
    return (
      <section className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
        Checking ingest paths...
      </section>
    )
  }
  const allPaths = [plan.local_default, ...plan.relay_paths]
  const recommendedPath =
    allPaths.find((path) => path.path_id === plan.recommended_path_id) ?? plan.local_default
  if (plan.relay_paths.length === 0) {
    return (
      <section className="rounded-md p-4" style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}>
        <div className="flex items-center justify-between gap-2">
          <h2 className="m-0 text-sm font-semibold">Remote ingest</h2>
          <StatusPill label="No source configured" tone="warn" />
        </div>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          No meeting source is configured for this channel yet. Add a camera, encoder, or
          sample source above before running pre-flight -- CivicCast has no listener at any
          default address until you do.
        </p>
      </section>
    )
  }
  return (
    <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">Remote ingest</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            Recommended: {recommendedPath.label}
          </p>
        </div>
        <StatusPill
          label={RELAY_HEALTH_LABEL[recommendedPath.health_state]}
          tone={toneFor(recommendedPath.health_state)}
        />
      </div>
      {plan.degraded_count > 0 && (
        <p className="m-0 mt-2 rounded-md px-2 py-1 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          {plan.degraded_count} remote path needs attention before it should be trusted for a meeting.
        </p>
      )}
      <div className="mt-3 grid gap-2">
        {allPaths.map((path) => (
          <article key={path.path_id} className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="m-0 text-sm font-semibold">{path.label}</h3>
                <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                  {RELAY_MODE_LABEL[path.mode]}{path.provider ? ` - ${path.provider}` : ''}
                </p>
              </div>
              <StatusPill
                label={RELAY_HEALTH_LABEL[path.health_state]}
                tone={toneFor(path.health_state)}
              />
            </div>
            <div className="cc-mono mt-2 truncate text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              {path.endpoint_url}
            </div>
            <p className="m-0 mt-2 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
              {pathDescription(path)}
            </p>
            {path.return_playback_url && (
              <div className="cc-mono mt-1 truncate text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                Return: {path.return_playback_url}
              </div>
            )}
            {path.operator_action && (
              <p className="m-0 mt-2 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
                <strong>Next step.</strong> {path.operator_action}
              </p>
            )}
            {path.risk_note && (
              <p className="m-0 mt-2 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
                {path.risk_note}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}

function SourceSetupGuidance({
  report,
  error,
}: {
  report: SourceSetupReport | undefined
  error: unknown
}) {
  if (error) {
    return (
      <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-warn-soft)' }}>
        <strong>No meeting source is ready yet.</strong>{' '}
        <Link to="/setup" className="font-semibold">
          Open Setup
        </Link>{' '}
        and choose a camera or test video.
      </div>
    )
  }
  if (!report) {
    return (
      <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
        Checking camera setup options...
      </div>
    )
  }
  return (
    <section className="grid gap-3 rounded-md p-4" style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}>
      <div>
        <h2 className="m-0 text-base font-semibold">Choose a camera or test source</h2>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          {report.next_step}
        </p>
        <Link
          to="/setup"
          className="mt-3 inline-flex rounded-md px-3 py-2 text-xs font-semibold no-underline"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          Open camera and test media setup
        </Link>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {report.options.map((option) => (
          <article
            key={option.id}
            className="rounded-md p-3"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="m-0 text-sm font-semibold">{option.label}</h3>
              {option.needs_it_help && (
                <StatusPill label="Needs IT help" tone="warn" />
              )}
            </div>
            <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              {option.best_for}
            </p>
            <ol className="m-0 mt-2 grid gap-1 pl-4 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              {option.operator_steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    </section>
  )
}

export function PreviewPanel({
  source,
}: {
  source: LiveSourceResponse | undefined
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">On-air preview</h2>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            CivicCast only shows source media here after server-side verification.
          </p>
        </div>
      </div>
      <div
        className="grid min-h-56 place-items-center rounded-md p-4"
        style={{
          background: 'var(--cc-warn-soft)',
          color: 'var(--cc-ink)',
          border: '1px solid var(--cc-line)',
        }}
      >
        <div className="max-w-md text-center">
          <div className="text-lg font-semibold">Source preview unavailable</div>
          <div className="mt-2 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            CivicCast has not verified incoming video or audio from{' '}
            <strong>{source?.name ?? 'the selected source'}</strong>. No simulated
            preview or audio meter is shown.
          </div>
          <div className="mt-3 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            <strong>Next step.</strong> Connect a real encoder or meeting source and
            run pre-flight. Start Live Stream remains blocked until a server-side
            media probe passes.
          </div>
        </div>
      </div>
    </section>
  )
}

export function PreflightList({ evaluation }: { evaluation: PreflightEvaluation | null }) {
  const checks = evaluation?.checks ?? []
  // Banner-wall fix (field survey 2026-08-30): every failed check used to carry
  // its own "DO NOT BROADCAST YET" pill, so a fresh box with several failures
  // read as a wall of identical red banners. The page verdict is stated ONCE in
  // the summary banner below; per-row pills render only when they say something
  // the verdict banner does not. Failed rows keep their severity via the red
  // border and their "Next step" line.
  const failedCount = checks.filter(
    (check) => readinessLabel(check.status) === READINESS_DO_NOT_BROADCAST_YET,
  ).length
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="m-0 text-sm font-semibold">Pre-flight checklist</h2>
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Every failed item includes the backend reason and a next action.
        </p>
      </div>
      {checks.length === 0 ? (
        <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
          Run pre-flight to populate the nine-check contract.
        </div>
      ) : (
        <>
        {failedCount > 0 && (
          <div
            className="rounded-md p-3 text-xs"
            role="note"
            style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
          >
            <strong className="block text-sm" style={{ color: 'var(--cc-err)' }}>
              {READINESS_DO_NOT_BROADCAST_YET}
            </strong>
            <span>
              {failedCount === 1
                ? '1 pre-flight check must pass'
                : `${failedCount} pre-flight checks must pass`}{' '}
              before this room can go live. Each failed item below says what to do next.
            </span>
          </div>
        )}
        <ul className="m-0 grid list-none gap-2 p-0">
          {checks.map((check) => (
            <li
              key={check.name}
              className="rounded-md p-3"
              style={{
                border: `1px solid ${
                  readinessLabel(check.status) === READINESS_DO_NOT_BROADCAST_YET
                    ? 'var(--cc-err)'
                    : 'var(--cc-line)'
                }`,
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">
                  {PREFLIGHT_LABELS[check.name] ?? check.name}
                </span>
                {readinessLabel(check.status) !== READINESS_DO_NOT_BROADCAST_YET && (
                  <StatusPill
                    label={readinessLabel(check.status)}
                    tone={toneForReadiness(check.status)}
                  />
                )}
              </div>
              {check.message && (
                <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                  {check.message}
                </div>
              )}
              {check.status === 'fail' && (
                <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                  <strong>Next step.</strong> {preflightNextStep(check.reason_code)}
                </div>
              )}
            </li>
          ))}
        </ul>
        </>
      )}
    </section>
  )
}

export function LiveRoomScreen() {
  const [session, setSession] = useState<LiveSessionResponse | null>(null)
  const [preflight, setPreflight] = useState<PreflightEvaluation | null>(null)
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [operatorConfirmed, setOperatorConfirmed] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
  const requestConfirm = (confirm: PendingConfirm) => setPendingConfirm(confirm)
  const confirmed = () => {
    pendingConfirm?.run()
    setPendingConfirm(null)
  }
  const [channelId, setChannelId] = useState<string>(() => {
    try {
      return window.localStorage.getItem(CHANNEL_STORAGE_KEY) ?? DEFAULT_CHANNEL_ID
    } catch {
      return DEFAULT_CHANNEL_ID
    }
  })
  const selectChannel = (next: string) => {
    setChannelId(next)
    try {
      window.localStorage.setItem(CHANNEL_STORAGE_KEY, next)
    } catch {
      // Persistence is a convenience; selection still applies this session.
    }
  }
  const queryClient = useQueryClient()
  const [editingSource, setEditingSource] = useState<LiveSourceResponse | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  // The server's current row when a 409 reveals a conflicting concurrent
  // edit -- display-only (WP-07 hostile-review finding N2). The operator's
  // typed field values must survive a 409, so this is never applied over
  // `editingSource`; it's shown alongside the fields that differ so the
  // operator can compare before deciding to save over it.
  const [editConflict, setEditConflict] = useState<LiveSourceResponse | null>(null)
  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    retry: false,
  })

  const sourcesQuery = useQuery<LiveSourceResponse[], Error>({
    queryKey: ['live-sources'],
    queryFn: listLiveSources,
    retry: false,
    // Readiness ages out of its (default 30s, min 5s) server-side TTL even
    // when nobody touches this screen. Session and ingest-plan state already
    // poll at 3s; without a poll here a "Delivering / checked N seconds ago"
    // pill could sit on screen well past the TTL that actually governs
    // takeover, silently telling the operator something the takeover gate no
    // longer believes. Polling at most every 10s keeps the display honest
    // without re-listing sources on every render.
    refetchInterval: 10_000,
  })
  const sourceSetupQuery = useQuery({
    queryKey: ['source-setup'],
    queryFn: getSourceSetup,
    retry: false,
  })
  const targetsQuery = useQuery({
    queryKey: ['recording-targets'],
    queryFn: listRecordingTargets,
    retry: false,
  })
  const ingestPlanQuery = useQuery<LiveIngestPlan, Error>({
    queryKey: ['live-ingest-plan', channelId],
    queryFn: () => getLiveIngestPlan(channelId),
    retry: false,
  })
  const safeQuery = useQuery({
    queryKey: ['safe-to-broadcast'],
    queryFn: getSafeToBroadcast,
    retry: false,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })

  const sources = sourcesQuery.data ?? EMPTY_SOURCES
  const canOperateMeeting =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'meeting_operator')
  const canEditSources =
    staffIdentityQuery.isSuccess && hasOperatorRole(staffIdentityQuery.data, 'setup_admin')
  // Matches the backend's POST /sources/{id}/probe gate exactly
  // (require_any_role("meeting_operator", "setup_admin")): the Check source
  // button must not render for an identity that can view the Live Room but
  // whose click would just 403.
  const canCheckSource =
    staffIdentityQuery.isSuccess &&
    (hasOperatorRole(staffIdentityQuery.data, 'meeting_operator') ||
      hasOperatorRole(staffIdentityQuery.data, 'setup_admin'))
  const selectedSource = useMemo(() => {
    if (sources.length === 0) return undefined
    return sources.find((source) => source.live_source_id === selectedSourceId) ?? sources[0]
  }, [selectedSourceId, sources])

  const runAction = async (work: () => Promise<LiveSessionResponse>) => {
    setActionError(null)
    try {
      const next = await work()
      setSession(next)
    } catch (err) {
      setActionError(apiMessage(err, 'The live-room action failed.'))
    }
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createLiveSession({
        live_session_id: SESSION_ID,
        channel_id: channelId,
        title: SESSION_TITLE,
        notes: 'Created from the operator live room.',
      }),
    onSuccess: setSession,
    onError: (err) => setActionError(apiMessage(err, 'Could not create session.')),
  })

  const preflightMutation = useMutation({
    mutationFn: () => {
      if (!session) throw new Error('Create a live session before pre-flight.')
      const payload: PreflightInputs = {
        live_session_id: session.live_session_id,
        live_source_id: selectedSource?.live_source_id ?? '',
        network_reachable: null,
        storage_free_bytes: null,
        ai_runtime_ready: null,
        operator_confirmed: operatorConfirmed,
      }
      return evaluateLivePreflight(session.live_session_id, payload)
    },
    onSuccess: setPreflight,
    onError: (err) => setActionError(apiMessage(err, 'Could not run pre-flight.')),
  })

  // WP-07: checking a source and editing one both change what the ingest plan
  // and the takeover gate will say about it, so both invalidate the two
  // queries that render readiness rather than patching local state -- the
  // server is the only thing that knows the applied TTL.
  const refreshReadiness = () => {
    void queryClient.invalidateQueries({ queryKey: ['live-sources'] })
    void queryClient.invalidateQueries({ queryKey: ['live-ingest-plan', channelId] })
  }

  const probeMutation = useMutation({
    mutationFn: (liveSourceId: string) => probeLiveSource(liveSourceId),
    onSuccess: (result) => {
      setActionError(null)
      // A failed check is a 200. Surface its reason here rather than letting
      // the card silently keep its previous state.
      if (!result.ok) setActionError(result.detail ?? 'The source check failed.')
      refreshReadiness()
    },
    onError: (err) => setActionError(apiMessage(err, 'Could not check the source.')),
  })

  const editMutation = useMutation({
    mutationFn: (payload: LiveSourceUpdate) => {
      if (!editingSource) throw new Error('No source is being edited.')
      return updateLiveSource(editingSource.live_source_id, payload)
    },
    onSuccess: () => {
      setEditError(null)
      setEditConflict(null)
      setEditingSource(null)
      refreshReadiness()
    },
    onError: async (err) => {
      // A 409 means someone else's edit landed first, and the form was still
      // holding the row_version that PATCH was built from. Resending the
      // same payload would just 409 again forever, so the next save needs
      // the current row_version -- but the operator's typed field values
      // must survive this, not be silently discarded and replaced with
      // whatever the server now has (hostile-review finding N2: an earlier
      // version of this fix remounted the form on the fresh row, which threw
      // away work in progress the moment two edits raced). Only
      // `row_version` advances on `editingSource`; every other field the
      // operator typed is untouched, and the fresh row is kept separately in
      // `editConflict` purely for the "Server now has" comparison text.
      if (err instanceof ApiError && err.status === 409 && editingSource) {
        try {
          const fresh = await getLiveSourceById(editingSource.live_source_id)
          setEditConflict(fresh)
          setEditingSource((prev) =>
            prev ? { ...prev, row_version: fresh.row_version } : prev,
          )
          setEditError(
            'Someone else changed this source while you were editing it. ' +
              "Your changes were kept — compare them with what the server now has, then save again.",
          )
        } catch (reloadErr) {
          setEditError(apiMessage(reloadErr, 'Could not save the source.'))
        }
        refreshReadiness()
        return
      }
      setEditError(apiMessage(err, 'Could not save the source.'))
    },
  })

  const stateMeta = session ? LIVE_STATE_META[session.state] : null
  const ready = preflight?.ready ?? false
  const loading = sourcesQuery.isLoading || targetsQuery.isLoading || ingestPlanQuery.isLoading
  const loadError = sourcesQuery.error ?? targetsQuery.error

  if (loadError) {
    return (
      <ErrorPanel
        title="Could not load live room."
        message={apiMessage(loadError, 'Live-room configuration failed to load.')}
      />
    )
  }

  return (
    <div className="flex flex-col gap-5 px-6 py-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
            Operator live room
          </div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">Live</h1>
          <p className="m-0 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Run pre-flight and start only after CivicCast verifies the source,
            storage, and network from the server.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {stateMeta ? (
            <StatusPill label={stateMeta.label} tone={stateMeta.tone} />
          ) : (
            <StatusPill label="No session" tone="neutral" />
          )}
          {preflight && <StatusPill label={ready ? 'Pre-flight ready' : 'Pre-flight blocked'} tone={ready ? 'ok' : 'err'} />}
        </div>
      </header>

      {actionError && <ErrorPanel title="Live action failed." message={actionError} />}

      <SafeToBroadcastPanel
        report={safeQuery.data}
        isLoading={safeQuery.isLoading || safeQuery.isFetching}
        error={safeQuery.error}
        onRetry={() => void safeQuery.refetch()}
      />

      {staffIdentityQuery.isSuccess && !canOperateMeeting && (
        <div className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          Live-room controls require the meeting operator role. Source status and readiness checks remain visible.
        </div>
      )}

      {loading ? (
        <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Loading live-room configuration...
        </div>
      ) : sources.length === 0 ? (
        <SourceSetupGuidance
          report={sourceSetupQuery.data}
          error={sourceSetupQuery.error}
        />
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex flex-col gap-5">
            <PreviewPanel source={selectedSource} />
            <SourceSwitcher
              sources={sources}
              selectedId={selectedSource?.live_source_id ?? ''}
              onSelect={setSelectedSourceId}
              onCheck={(id) => probeMutation.mutate(id)}
              onEdit={(source) => {
                setEditError(null)
                setEditConflict(null)
                setEditingSource(source)
              }}
              checkingId={probeMutation.isPending ? probeMutation.variables : null}
              canEdit={canEditSources}
              canCheck={canCheckSource}
            />
            {editingSource ? (
              <SourceEditForm
                // Keyed on the source id ONLY, deliberately not on
                // row_version: remounting on a 409's row_version bump would
                // reset the form's local field state back to the (now
                // fresh-but-not-what-the-operator-typed) source prop,
                // discarding whatever they'd typed (hostile-review finding
                // N2). This key remounts only when editing switches to a
                // genuinely different source.
                key={editingSource.live_source_id}
                source={editingSource}
                conflict={editConflict}
                onCancel={() => {
                  setEditError(null)
                  setEditConflict(null)
                  setEditingSource(null)
                }}
                onSave={(payload) => editMutation.mutate(payload)}
                saving={editMutation.isPending}
                error={editError}
              />
            ) : null}
            <RelayStatusPanel plan={ingestPlanQuery.data} error={ingestPlanQuery.error} />
          </div>
          <aside className="flex flex-col gap-4">
            <section className="rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
              <h2 className="m-0 text-sm font-semibold">Session controls</h2>
              <div className="mt-3 flex flex-col gap-1">
                <label
                  htmlFor="live-room-channel"
                  className="text-xs font-semibold"
                  style={{ color: 'var(--cc-ink-2)' }}
                >
                  Broadcast channel
                </label>
                <select
                  id="live-room-channel"
                  value={channelId}
                  onChange={(event) => selectChannel(event.target.value)}
                  disabled={session != null}
                  className="rounded-md px-2 py-2 text-sm"
                  style={{
                    background: 'var(--cc-surface-2)',
                    border: '1px solid var(--cc-line)',
                    color: 'var(--cc-ink)',
                  }}
                >
                  {(channelsQuery.data ?? []).map((channel) => (
                    <option key={channel.channel_id} value={channel.channel_id}>
                      {channel.channel_id}
                    </option>
                  ))}
                  {!(channelsQuery.data ?? []).some(
                    (channel) => channel.channel_id === channelId,
                  ) && <option value={channelId}>{channelId}</option>}
                </select>
                <span className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                  {session
                    ? 'Channel is fixed while a session exists.'
                    : 'The session and ingest plan use this channel.'}
                </span>
              </div>
              <div className="mt-3 flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => createMutation.mutate()}
                  disabled={!canOperateMeeting || createMutation.isPending || session != null}
                  className="rounded-md px-3 py-2 text-sm font-semibold"
                  style={{ background: canOperateMeeting && !session ? 'var(--cc-brand)' : 'var(--cc-surface-3)', color: canOperateMeeting && !session ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)' }}
                >
                  Create live session
                </button>
                <button
                  type="button"
                  onClick={() => runAction(() => startLivePreflight(session!.live_session_id))}
                  disabled={!canOperateMeeting || !session || session.state !== 'idle'}
                  className="rounded-md px-3 py-2 text-sm font-semibold"
                  style={{ background: canOperateMeeting && session?.state === 'idle' ? 'var(--cc-info)' : 'var(--cc-surface-3)', color: canOperateMeeting && session?.state === 'idle' ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)' }}
                >
                  Start pre-flight
                </button>
                <label className="flex items-start gap-2 rounded-md p-2 text-xs" style={{ background: 'var(--cc-surface-2)' }}>
                  <input
                    type="checkbox"
                    checked={operatorConfirmed}
                    disabled={!canOperateMeeting}
                    onChange={(event) => setOperatorConfirmed(event.target.checked)}
                  />
                  Operator confirms the meeting details and acknowledges the
                  server-side pre-flight result.
                </label>
                <button
                  type="button"
                  onClick={() => preflightMutation.mutate()}
                  disabled={!canOperateMeeting || !session || session.state !== 'preflight'}
                  className="rounded-md px-3 py-2 text-sm font-semibold"
                  style={{ background: canOperateMeeting && session?.state === 'preflight' ? 'var(--cc-brand)' : 'var(--cc-surface-3)', color: canOperateMeeting && session?.state === 'preflight' ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)' }}
                >
                  Run pre-flight
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (!session || !selectedSource) return
                    const payload: PreflightInputs = {
                      live_session_id: session.live_session_id,
                      live_source_id: selectedSource.live_source_id,
                      network_reachable: null,
                      storage_free_bytes: null,
                      ai_runtime_ready: null,
                      operator_confirmed: operatorConfirmed,
                    }
                    void runAction(() => goLiveOnAir(session.live_session_id, payload))
                  }}
                  disabled={!canOperateMeeting || !session || session.state !== 'preflight' || !ready}
                  className="rounded-md px-3 py-2 text-sm font-semibold"
                  style={{ background: canOperateMeeting && session?.state === 'preflight' && ready ? 'var(--cc-live)' : 'var(--cc-surface-3)', color: canOperateMeeting && session?.state === 'preflight' && ready ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)' }}
                >
                  Start Live Stream
                </button>
                <button
                  type="button"
                  onClick={() =>
                    requestConfirm({
                      title: 'End the live stream?',
                      body: 'Residents watching the live stream lose it immediately. The session moves to finalization and cannot be resumed from here — start a new live session to go live again.',
                      confirmLabel: 'End live stream',
                      run: () => void runAction(() => endLiveBroadcast(session!.live_session_id)),
                    })
                  }
                  disabled={!canOperateMeeting || !session || session.state !== 'on_air'}
                  className="rounded-md px-3 py-2 text-sm font-semibold"
                  style={{ background: canOperateMeeting && session?.state === 'on_air' ? 'var(--cc-err)' : 'var(--cc-surface-3)', color: canOperateMeeting && session?.state === 'on_air' ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)' }}
                >
                  End Live Stream
                </button>
              </div>
            </section>
            {session && (
              <FinalizationPanel session={session} onSessionRefresh={setSession} />
            )}
            <section className="rounded-md p-4 text-xs" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}>
              Recording targets: <strong>{targetsQuery.data?.length ?? 0}</strong>
            </section>
          </aside>
        </div>
      )}

      <PreflightList evaluation={preflight} />

      {pendingConfirm && (
        <ConfirmDialog
          title={pendingConfirm.title}
          body={pendingConfirm.body}
          confirmLabel={pendingConfirm.confirmLabel}
          tone={pendingConfirm.tone}
          onConfirm={confirmed}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}
