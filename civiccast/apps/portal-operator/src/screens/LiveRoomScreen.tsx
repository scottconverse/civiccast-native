import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
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
  getSafeToBroadcast,
  getSourceSetup,
  goLiveOnAir,
  listChannelProfiles,
  listLiveSources,
  listRecordingTargets,
  retryLiveFinalization,
  startLivePreflight,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { RadioCardGroup } from '../components/RadioCardGroup'
import { readinessLabel, toneForReadiness } from './status-language'
import {
  LIVE_STATE_META,
  PREFLIGHT_LABELS,
  RELAY_HEALTH_LABEL,
  RELAY_MODE_LABEL,
  SOURCE_TYPE_LABEL,
  type LiveIngestHealth,
  type LiveIngestPath,
  type LiveIngestPlan,
  type LiveSessionResponse,
  type LiveSourceResponse,
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

function SourceSwitcher({
  sources,
  selectedId,
  onSelect,
}: {
  sources: LiveSourceResponse[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="m-0 text-sm font-semibold">Source switcher</h2>
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Arrow keys move between configured meeting sources.
        </p>
      </div>
      <RadioCardGroup
        label="Live source"
        options={sources.map((source) => ({
          id: source.live_source_id,
          label: source.name,
          trailing: (
            <StatusPill
              label={SOURCE_TYPE_LABEL[source.source_type]}
              tone="neutral"
            />
          ),
          description: (
            <span
              className="cc-mono block truncate"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              {source.endpoint_url}
            </span>
          ),
        }))}
        value={selectedId}
        onChange={onSelect}
        className="grid gap-2 md:grid-cols-2"
        buttonClassName="min-h-24 rounded-md p-3 text-left"
        getDescriptionColor={() => 'var(--cc-ink-3)'}
      />
    </section>
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
        <ul className="m-0 grid list-none gap-2 p-0">
          {checks.map((check) => (
            <li
              key={check.name}
              className="rounded-md p-3"
              style={{ border: '1px solid var(--cc-line)' }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">
                  {PREFLIGHT_LABELS[check.name] ?? check.name}
                </span>
                <StatusPill
                  label={readinessLabel(check.status)}
                  tone={toneForReadiness(check.status)}
                />
              </div>
              {check.message && (
                <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                  {check.message}
                </div>
              )}
              {check.status === 'fail' && (
                <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                  <strong>Next step.</strong> Resolve {check.reason_code ?? check.name} and
                  re-run pre-flight.
                </div>
              )}
            </li>
          ))}
        </ul>
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
  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    retry: false,
  })

  const sourcesQuery = useQuery<LiveSourceResponse[], Error>({
    queryKey: ['live-sources'],
    queryFn: listLiveSources,
    retry: false,
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
            />
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
                  onClick={() => runAction(() => endLiveBroadcast(session!.live_session_id))}
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
    </div>
  )
}
