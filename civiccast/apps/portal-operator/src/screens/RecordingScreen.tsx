// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S21 Operator console: scheduled recording (slice 4).
//
// Single-page screen that lets a station operator forward-schedule captures of
// live inputs (SDI/HDMI/NDI) and network streams (RTSP/SRT/HLS/RTMP/MPEG-TS),
// kick off ad-hoc one-shot captures via Record-Now, and track the resulting
// recording-job history. The production backend owns capture, finalization,
// and alerting; this screen configures and observes those workflows. If a
// deployment override leaves the runtime unavailable, /record-now returns 503
// and we surface a degraded-mode banner so the rest of the screen still works.
//
// Layout, top to bottom:
//
//   0. (Conditional) degraded-mode banner when /record-now returns 503 — the
//      operator can still create + edit schedules; jobs will materialize once
//      the engine ships.
//
//   1. Schedules table — name, source (humanized), recurrence (humanized),
//      duration (HH:MM:SS), enabled (badge), actions (Record now / Edit /
//      Delete). support_admin sees the table read-only (no actions).
//
//   2. Create / edit form — slug schedule_id (read-only after create), name,
//      source-kind selector with conditional input_id vs uri, recurrence-kind
//      selector with conditional one_shot start vs weekly weekdays+time,
//      duration as "HH:MM:SS" (converted to seconds on submit), encoder
//      profile, loudness regime, optional target series, enabled toggle.
//
//   3. Jobs table — planned start (local time), source (humanized), state
//      (color-coded badge), duration (computed), bytes written (humanized),
//      asset id (link when present), failure reason, Stop action when active.
//      Filter row (state / schedule_id / limit) + Refresh + 5s auto-refresh
//      while any job is in a live state.
//
// Role gate: setup_admin, meeting_operator, and support_admin can reach this
// screen (matches the Sidebar config); support_admin is read-only.

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  createRecordingSchedule,
  deleteRecordingSchedule,
  getStaffIdentity,
  listRecordingJobs,
  listRecordingSchedules,
  recordNow,
  stopRecordingJob,
  updateRecordingSchedule,
} from '../api/client'
import type {
  RecordingJob,
  RecordingJobState,
  RecordingSchedule,
  RecordingScheduleInput,
  RecordingScheduleUpdate,
  RecordingSource,
  RecordingSourceKind,
  RecurrenceSpec,
} from '../api/client'
import type { StaffIdentityResponse } from '../types/api.generated'
import { hasRole } from './contribution-format'
import {
  formatDurationHMS,
  formatFirePreview,
  formatPlannedStart,
  humanizeBytes,
  humanizeRecurrence,
  humanizeSource,
  jobDuration,
  LIVE_SOURCE_KINDS,
  nextOneShotFireTimes,
  nextWeeklyFireTimes,
  parseDurationHMS,
  utcDateTimeLocalToLocalEcho,
  utcHHMMToLocalEcho,
} from './recording-format'

const VIEW_ROLES = ['setup_admin', 'meeting_operator', 'support_admin']
const WRITE_ROLES = ['setup_admin', 'meeting_operator']
// UX-19: hard-coded single-station id. Acceptable for dev / single-station
// deployments; track for the day a multi-tenant operator console ships
// (replace with a station selector sourced from staff identity).
const DEFAULT_STATION_ID = 'civiccast-station'

// Some dev / lab deployments can still force the recording runtime offline.
// /record-now surfaces that with a 503; the screen catches that exact case and
// renders the top banner without breaking save/edit/delete flows.
const ENGINE_UNWIRED_STATUS = 503

// UX-5: split the source-kind dropdown into two optgroups so the operator
// scans by category first (live capture card vs network ingest). The setup
// workflow on the right side of the form is materially different between
// the two (Input ID vs URI).
const LIVE_SOURCE_OPTIONS: Array<{ value: RecordingSourceKind; label: string }> = [
  { value: 'sdi', label: 'SDI' },
  { value: 'hdmi', label: 'HDMI' },
  { value: 'ndi', label: 'NDI' },
]

const NETWORK_SOURCE_OPTIONS: Array<{ value: RecordingSourceKind; label: string }> = [
  { value: 'rtsp', label: 'RTSP' },
  { value: 'srt', label: 'SRT' },
  { value: 'hls', label: 'HLS' },
  { value: 'rtmp', label: 'RTMP' },
  { value: 'mpegts', label: 'MPEG-TS' },
]

// UX-3: there's no public encoder-profile registry endpoint on the backend
// today. We seed a static suggestion list via <datalist> so the operator
// gets discoverability + autocomplete without having to memorize a slug.
// When an admin endpoint exposes the live profile list, swap this for a
// react-query against it and keep the help text.
const ENCODER_PROFILE_SUGGESTIONS: ReadonlyArray<string> = [
  'default',
  'copy',
  'h264-1080p',
  'h264-720p',
  'hw-h264-1080p',
  'hw-h264-720p',
]

// Weekly-recurrence weekday checkbox labels. Mon-first ordering matches the
// backend's `weekdays: int[]` convention where 0 = Monday … 6 = Sunday.
const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const LOUDNESS_OPTIONS = [
  { value: 'inherit', label: 'Inherit station default' },
  { value: 'copy', label: 'Copy source audio' },
  { value: 'atsc-a85', label: 'Cable / ATSC A/85 (-24 LKFS)' },
  { value: 'ebu-r128', label: 'Broadcast / EBU R128 (-23 LUFS)' },
  { value: 'streaming', label: 'Streaming (-16 LUFS)' },
]

// UX-4: inline help under the loudness select. A first-time operator at a
// PEG station knows their delivery channel ("cable headend") but typically
// not the LUFS target. These one-liners pick the right regime by what the
// audio is going to.
const LOUDNESS_HELP: Record<string, string> = {
  inherit: 'Use the station-wide default configured in Setup.',
  copy: 'Leave the source audio untouched.',
  'atsc-a85': 'ATSC A/85. Required by US cable headends and the CALM Act.',
  'ebu-r128': 'EBU R128. For broadcast and public-media exchange workflows.',
  streaming: 'For YouTube, Vimeo, and most OTT/web players.',
}

// While any of these states is present in the jobs list, the auto-refresh
// timer keeps polling. The cadence is intentionally modest (5 s) so the screen
// doesn't hammer the API while still feeling live during a capture.
const ACTIVE_JOB_STATES: ReadonlySet<RecordingJobState> = new Set([
  'scheduled',
  'arming',
  'recording',
  'finalizing',
])

const AUTO_REFRESH_MS = 5000

// State -> tone mapping for the jobs-table badge. Mirrors the convention used
// in PaywallScreen / contribution-format (ok = green, warn = yellow,
// info = blue, err = red).
type Tone = 'neutral' | 'ok' | 'warn' | 'info' | 'err'

const STATE_TONE: Record<RecordingJobState, Tone> = {
  scheduled: 'info',
  arming: 'warn',
  recording: 'ok',
  finalizing: 'warn',
  done: 'ok',
  failed: 'err',
  skipped: 'neutral',
}

const TONE_COLORS: Record<Tone, { bg: string; bd: string; fg: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)', fg: 'var(--cc-ink-3)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)', fg: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)', fg: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)', fg: 'var(--cc-info)' },
  err: { bg: 'var(--cc-err-soft)', bd: 'var(--cc-err)', fg: 'var(--cc-err)' },
}

const INPUT_STYLE: CSSProperties = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  const role = tone === 'warn' || tone === 'err' ? 'alert' : 'status'
  return (
    <div
      role={role}
      className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {children}
    </div>
  )
}

function StateBadge({ state }: { state: RecordingJobState }) {
  const tone = STATE_TONE[state]
  const c = TONE_COLORS[tone]
  return (
    <span
      data-testid={`job-state-badge-${state}`}
      className="rounded-md px-2 py-0.5 text-xs font-semibold"
      style={{ background: c.bg, border: `1px solid ${c.bd}`, color: c.fg }}
    >
      {state}
    </span>
  )
}

// --- Screen entry-point (role gate) ----------------------------------------

export function RecordingScreen() {
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })

  if (identityQuery.isLoading) {
    return (
      <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        Loading…
      </div>
    )
  }
  if (identityQuery.isError) {
    return (
      <div className="px-6 py-10">
        <Banner tone="warn">
          Could not load your staff identity (
          {apiMessage(identityQuery.error, 'request failed')}). Check that you are signed in
          and the local API is running, then retry.
        </Banner>
      </div>
    )
  }
  const canView = hasRole(identityQuery.data, VIEW_ROLES)
  if (!canView) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Forbidden — scheduled recording is an operator / setup-admin / support-admin
          surface. Ask your station admin for access.
        </Banner>
      </div>
    )
  }
  const canWrite = hasRole(identityQuery.data, WRITE_ROLES)
  return <RecordingBody canWrite={canWrite} />
}

// --- Screen body ------------------------------------------------------------

interface JobsFilterState {
  state: RecordingJobState | ''
  schedule_id: string
  limit: number
}

const DEFAULT_JOBS_FILTER: JobsFilterState = {
  state: '',
  schedule_id: '',
  limit: 50,
}

function RecordingBody({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient()

  const schedulesQuery = useQuery<RecordingSchedule[]>({
    queryKey: ['recording-schedules'],
    queryFn: listRecordingSchedules,
    retry: false,
  })

  // Jobs filter — the screen owns this; the query key includes the filter so
  // react-query refetches when the operator narrows. We don't push the filter
  // into the URL (sister screens like AssetsScreen also keep filters in
  // memory) but the limit is bounded so the table stays manageable.
  const [jobsFilter, setJobsFilter] = useState<JobsFilterState>(DEFAULT_JOBS_FILTER)

  const jobsQuery = useQuery<RecordingJob[]>({
    queryKey: ['recording-jobs', jobsFilter],
    queryFn: () =>
      listRecordingJobs({
        state: jobsFilter.state === '' ? undefined : jobsFilter.state,
        schedule_id: jobsFilter.schedule_id || undefined,
        limit: jobsFilter.limit,
      }),
    retry: false,
  })

  // Auto-refresh while any job is "active" (scheduled / arming / recording /
  // finalizing). We use a setInterval rather than react-query's built-in
  // refetchInterval so the cadence is decoupled from the row count and we can
  // reason about it from tests. Cleared the instant no active job remains.
  const anyActive = useMemo(
    () => (jobsQuery.data ?? []).some((j) => ACTIVE_JOB_STATES.has(j.state)),
    [jobsQuery.data],
  )
  // UX-6: visible refresh state. The operator can pause auto-refresh while
  // reading a failure_reason without losing the rest of the screen, and we
  // surface the last refresh time so they know how stale the table is.
  const [autoRefreshPaused, setAutoRefreshPaused] = useState<boolean>(false)
  // `dataUpdatedAt` is react-query's authoritative last-success timestamp;
  // we derive the display Date from it on every render rather than mirror
  // it into state (avoids a cascading setState in an effect).
  const lastRefreshedAt = useMemo<Date | null>(
    () => (jobsQuery.dataUpdatedAt ? new Date(jobsQuery.dataUpdatedAt) : null),
    [jobsQuery.dataUpdatedAt],
  )
  // Hold the live refetch in state so the interval below always calls the
  // current closure without making the interval-effect re-fire on every
  // refetch identity change. Updated inside an effect (never during render).
  const jobsRefetch = jobsQuery.refetch
  useEffect(() => {
    if (!anyActive || autoRefreshPaused) return undefined
    const id = setInterval(() => {
      void jobsRefetch()
    }, AUTO_REFRESH_MS)
    return () => clearInterval(id)
  }, [anyActive, autoRefreshPaused, jobsRefetch])

  // Top-of-screen degraded-mode banner state. Set when ANY /record-now call
  // returns 503; cleared on a successful call.
  const [engineUnwired, setEngineUnwired] = useState<boolean>(false)

  // Edit-form state. `editingId` of null = create mode; otherwise = patch
  // mode against that schedule_id. The form snapshot lives below in
  // <ScheduleForm /> so we don't re-derive it from props on every keystroke.
  const [editingId, setEditingId] = useState<string | null>(null)
  const editingSchedule =
    editingId && (schedulesQuery.data ?? []).find((s) => s.schedule_id === editingId)

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  // UX-1: Stop on a `recording` job kills a live capture. Mirror the Delete
  // 2-step confirm so a misclick mid-meeting can't terminate the recording.
  const [confirmStopJobId, setConfirmStopJobId] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: (payload: RecordingScheduleInput) => createRecordingSchedule(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recording-schedules'] }),
  })

  const updateMut = useMutation({
    mutationFn: (args: { id: string; payload: RecordingScheduleUpdate }) =>
      updateRecordingSchedule(args.id, args.payload),
    onSuccess: () => {
      setEditingId(null)
      qc.invalidateQueries({ queryKey: ['recording-schedules'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRecordingSchedule(id),
    onSuccess: () => {
      setConfirmDeleteId(null)
      qc.invalidateQueries({ queryKey: ['recording-schedules'] })
    },
  })

  const recordNowMut = useMutation({
    mutationFn: (id: string) => recordNow(id),
    onSuccess: () => {
      setEngineUnwired(false)
      qc.invalidateQueries({ queryKey: ['recording-jobs'] })
    },
    onError: (err) => {
      // A 503 from an unavailable runtime is a known-degraded state, not a bug.
      // We surface the banner instead of a red-line error toast so the
      // operator can keep working on schedules.
      if (err instanceof ApiError && err.status === ENGINE_UNWIRED_STATUS) {
        setEngineUnwired(true)
      }
    },
  })

  const stopMut = useMutation({
    mutationFn: (id: string) => stopRecordingJob(id),
    onSuccess: () => {
      setConfirmStopJobId(null)
      qc.invalidateQueries({ queryKey: ['recording-jobs'] })
    },
  })

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Scheduled recording</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Forward-schedule captures of live inputs and network streams, or kick off an
          ad-hoc one-shot via Record now. The production runtime owns capture,
          finalization, and alerts; this screen owns configuration and history.
        </p>
      </div>

      {engineUnwired && (
        <Banner tone="warn">
          Scheduled recording runtime is unavailable in this deployment. Schedules can
          still be created; jobs will materialize when the runtime is enabled.
        </Banner>
      )}

      <SchedulesSection
        schedules={schedulesQuery.data ?? []}
        isLoading={schedulesQuery.isLoading}
        loadError={
          schedulesQuery.isError
            ? apiMessage(schedulesQuery.error, 'Could not load schedules.')
            : null
        }
        canWrite={canWrite}
        editingId={editingId}
        confirmDeleteId={confirmDeleteId}
        deleting={deleteMut.isPending}
        recordingNowId={recordNowMut.isPending ? (recordNowMut.variables ?? null) : null}
        recordNowError={
          recordNowMut.isError && !(recordNowMut.error instanceof ApiError &&
            recordNowMut.error.status === ENGINE_UNWIRED_STATUS)
            ? apiMessage(recordNowMut.error, 'Record now failed.')
            : null
        }
        engineUnwired={engineUnwired}
        onEdit={(id) => setEditingId(id)}
        onArmDelete={(id) => setConfirmDeleteId(id)}
        onCancelDelete={() => setConfirmDeleteId(null)}
        onConfirmDelete={(id) => deleteMut.mutate(id)}
        onRecordNow={(id) => recordNowMut.mutate(id)}
      />

      {canWrite && (
        <ScheduleForm
          key={editingSchedule ? editingSchedule.schedule_id : 'new'}
          editing={editingSchedule || null}
          submitting={createMut.isPending || updateMut.isPending}
          submitError={
            createMut.isError
              ? apiMessage(createMut.error, 'Could not create schedule.')
              : updateMut.isError
                ? apiMessage(updateMut.error, 'Could not update schedule.')
                : null
          }
          onCancelEdit={() => setEditingId(null)}
          onSubmit={(payload, isUpdate) => {
            if (isUpdate && editingSchedule) {
              updateMut.mutate({ id: editingSchedule.schedule_id, payload: payload })
            } else {
              createMut.mutate(payload as RecordingScheduleInput)
            }
          }}
        />
      )}

      <JobsSection
        jobs={jobsQuery.data ?? []}
        isLoading={jobsQuery.isLoading}
        isFetching={jobsQuery.isFetching}
        loadError={
          jobsQuery.isError ? apiMessage(jobsQuery.error, 'Could not load jobs.') : null
        }
        filter={jobsFilter}
        canWrite={canWrite}
        anyActive={anyActive}
        autoRefreshPaused={autoRefreshPaused}
        lastRefreshedAt={lastRefreshedAt}
        stoppingId={stopMut.isPending ? (stopMut.variables ?? null) : null}
        confirmStopJobId={confirmStopJobId}
        onFilterChange={setJobsFilter}
        onRefresh={() => jobsQuery.refetch()}
        onToggleAutoRefresh={() => setAutoRefreshPaused((p) => !p)}
        onArmStop={(id) => setConfirmStopJobId(id)}
        onCancelStop={() => setConfirmStopJobId(null)}
        onConfirmStop={(id) => stopMut.mutate(id)}
      />
    </div>
  )
}

// --- Schedules table --------------------------------------------------------

function SchedulesSection({
  schedules,
  isLoading,
  loadError,
  canWrite,
  editingId,
  confirmDeleteId,
  deleting,
  recordingNowId,
  recordNowError,
  engineUnwired,
  onEdit,
  onArmDelete,
  onCancelDelete,
  onConfirmDelete,
  onRecordNow,
}: {
  schedules: RecordingSchedule[]
  isLoading: boolean
  loadError: string | null
  canWrite: boolean
  editingId: string | null
  confirmDeleteId: string | null
  deleting: boolean
  recordingNowId: string | null
  recordNowError: string | null
  engineUnwired: boolean
  onEdit: (id: string) => void
  onArmDelete: (id: string) => void
  onCancelDelete: () => void
  onConfirmDelete: (id: string) => void
  onRecordNow: (id: string) => void
}) {
  // Client-side sort by name keeps the table stable across refetches. The
  // backend's order is "as inserted" — fine for a small list but harder to
  // scan once a station has 20+ schedules.
  const sorted = useMemo(
    () => [...schedules].sort((a, b) => a.name.localeCompare(b.name)),
    [schedules],
  )

  return (
    <section
      aria-label="Recording schedules"
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">Schedules</h2>

      {loadError && <Banner tone="warn">{loadError}</Banner>}
      {recordNowError && <Banner tone="warn">{recordNowError}</Banner>}

      {isLoading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading schedules…
        </p>
      ) : sorted.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No recording schedules yet — create one below.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            {/* UX-17: screen-reader caption for table-navigation mode. */}
            <caption className="sr-only">Recording schedules</caption>
            <thead>
              <tr style={{ color: 'var(--cc-ink-3)' }}>
                <th className="py-1 pr-3 font-semibold">Name</th>
                <th className="py-1 pr-3 font-semibold">Source</th>
                <th className="py-1 pr-3 font-semibold">Recurrence</th>
                <th className="py-1 pr-3 font-semibold">Duration</th>
                <th className="py-1 pr-3 font-semibold">Enabled</th>
                {canWrite && <th className="py-1 pr-3 font-semibold">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => {
                // UX-14: drop `text-stone-400` (borderline WCAG AA against
                // typical surface tokens). The "disabled" status pill plus a
                // left-border accent already convey the state at full ink
                // contrast, so the eye still lands on it.
                const isEditing = editingId === s.schedule_id
                const isConfirming = confirmDeleteId === s.schedule_id
                return (
                  <tr
                    key={s.schedule_id}
                    style={{
                      borderTop: '1px solid var(--cc-line)',
                      borderLeft: s.enabled
                        ? undefined
                        : '3px solid var(--cc-line)',
                    }}
                  >
                    <td className="py-1.5 pr-3">
                      <div className="font-medium">{s.name}</div>
                      <div className="text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                        {s.schedule_id}
                      </div>
                    </td>
                    <td className="py-1.5 pr-3">{humanizeSource(s.source)}</td>
                    <td className="py-1.5 pr-3">{humanizeRecurrence(s.recurrence)}</td>
                    <td className="py-1.5 pr-3">{formatDurationHMS(s.duration_seconds)}</td>
                    <td className="py-1.5 pr-3">
                      <StatusPill ok={s.enabled} okLabel="enabled" offLabel="disabled" />
                    </td>
                    {canWrite && (
                      <td className="py-1.5 pr-3">
                        <div className="flex flex-wrap items-center gap-1">
                          <button
                            type="button"
                            aria-label={`Record now from ${s.name}`}
                            disabled={
                              !s.enabled ||
                              engineUnwired ||
                              recordingNowId === s.schedule_id
                            }
                            onClick={() => onRecordNow(s.schedule_id)}
                            className="rounded-md px-2 py-1 text-xs font-medium disabled:opacity-50"
                            style={{
                              background: 'var(--cc-brand)',
                              color: 'var(--cc-brand-ink)',
                            }}
                          >
                            {recordingNowId === s.schedule_id ? 'Starting…' : 'Record now'}
                          </button>
                          <button
                            type="button"
                            aria-label={`Edit schedule ${s.name}`}
                            onClick={() => onEdit(s.schedule_id)}
                            className="rounded-md px-2 py-1 text-xs font-medium"
                            style={{
                              background: 'var(--cc-surface)',
                              border: '1px solid var(--cc-line)',
                            }}
                          >
                            {isEditing ? 'Editing' : 'Edit'}
                          </button>
                          {isConfirming ? (
                            <>
                              <button
                                type="button"
                                aria-label={`Confirm delete schedule ${s.name}`}
                                disabled={deleting}
                                onClick={() => onConfirmDelete(s.schedule_id)}
                                className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
                                style={{
                                  background: 'var(--cc-err-soft)',
                                  border: '1px solid var(--cc-err)',
                                }}
                              >
                                {deleting ? 'Deleting…' : 'Confirm delete'}
                              </button>
                              <button
                                type="button"
                                onClick={onCancelDelete}
                                className="rounded-md px-2 py-1 text-xs font-medium"
                                style={{
                                  background: 'var(--cc-surface)',
                                  border: '1px solid var(--cc-line)',
                                }}
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              aria-label={`Delete schedule ${s.name}`}
                              onClick={() => onArmDelete(s.schedule_id)}
                              className="rounded-md px-2 py-1 text-xs font-medium"
                              style={{
                                background: 'var(--cc-surface)',
                                border: '1px solid var(--cc-line)',
                              }}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function StatusPill({
  ok,
  okLabel,
  offLabel,
}: {
  ok: boolean
  okLabel: string
  offLabel: string
}) {
  const tone: Tone = ok ? 'ok' : 'neutral'
  const c = TONE_COLORS[tone]
  return (
    <span
      className="rounded-md px-1.5 py-0.5 text-[11px] font-semibold"
      style={{ background: c.bg, border: `1px solid ${c.bd}`, color: c.fg }}
    >
      {ok ? okLabel : offLabel}
    </span>
  )
}

// --- Schedule create / edit form --------------------------------------------

interface ScheduleFormState {
  schedule_id: string
  name: string
  source_kind: RecordingSourceKind
  input_id: string
  uri: string
  recurrence_kind: 'one_shot' | 'weekly'
  one_shot_start: string
  weekly_days: boolean[]
  weekly_time: string
  duration_text: string
  encoder_profile: string
  loudness_regime: string
  target_series: string
  enabled: boolean
}

function emptyFormState(): ScheduleFormState {
  return {
    schedule_id: '',
    name: '',
    source_kind: 'sdi',
    input_id: '',
    uri: '',
    recurrence_kind: 'one_shot',
    one_shot_start: '',
    weekly_days: [false, false, false, false, false, false, false],
    weekly_time: '',
    duration_text: '01:00:00',
    encoder_profile: 'default',
    loudness_regime: 'inherit',
    target_series: '',
    enabled: true,
  }
}

function stateFromSchedule(s: RecordingSchedule): ScheduleFormState {
  const weeklyDays = [false, false, false, false, false, false, false]
  let weeklyTime = ''
  let oneShotStart = ''
  if (s.recurrence.kind === 'weekly') {
    for (const d of s.recurrence.weekdays) {
      if (d >= 0 && d < 7) weeklyDays[d] = true
    }
    weeklyTime = s.recurrence.time_hhmm
  } else {
    // Use the first 16 chars (YYYY-MM-DDTHH:MM) for the datetime-local input.
    oneShotStart = s.recurrence.start.slice(0, 16)
  }
  return {
    schedule_id: s.schedule_id,
    name: s.name,
    source_kind: s.source.kind,
    input_id: s.source.input_id ?? '',
    uri: s.source.uri ?? '',
    recurrence_kind: s.recurrence.kind,
    one_shot_start: oneShotStart,
    weekly_days: weeklyDays,
    weekly_time: weeklyTime,
    duration_text: formatDurationHMS(s.duration_seconds),
    encoder_profile: s.encoder_profile,
    loudness_regime: s.loudness_regime,
    target_series: s.target_series ?? '',
    enabled: s.enabled,
  }
}

interface ValidationErrors {
  schedule_id?: string
  name?: string
  source?: string
  recurrence?: string
  duration?: string
  encoder_profile?: string
}

function validateForm(state: ScheduleFormState): ValidationErrors {
  const errs: ValidationErrors = {}
  if (!state.schedule_id.trim() || !/^[a-z0-9][a-z0-9-]*$/.test(state.schedule_id.trim())) {
    errs.schedule_id = 'Slug required: lowercase letters, digits, hyphens.'
  }
  if (!state.name.trim()) errs.name = 'Name is required.'
  if ((LIVE_SOURCE_KINDS as readonly string[]).includes(state.source_kind)) {
    if (!state.input_id.trim()) errs.source = 'Input ID is required for live sources.'
  } else {
    if (!state.uri.trim()) errs.source = 'URI is required for network streams.'
  }
  if (state.recurrence_kind === 'one_shot') {
    if (!state.one_shot_start.trim()) errs.recurrence = 'Start time is required.'
  } else {
    if (!state.weekly_days.some(Boolean))
      errs.recurrence = 'Pick at least one weekday.'
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(state.weekly_time.trim()))
      errs.recurrence = errs.recurrence ?? 'Time must be HH:MM (24h UTC).'
  }
  if (parseDurationHMS(state.duration_text) == null) {
    // UX-9: spell out the rule the operator just hit. The parser requires
    // two-digit minute / second fields so "1:5:0" silently fails — name it.
    errs.duration =
      'Duration must be HH:MM:SS — minutes and seconds need two digits (e.g. 01:05:00 not 1:5:0).'
  }
  if (!state.encoder_profile.trim()) errs.encoder_profile = 'Quality preset is required.'
  return errs
}

function ScheduleForm({
  editing,
  submitting,
  submitError,
  onCancelEdit,
  onSubmit,
}: {
  editing: RecordingSchedule | null
  submitting: boolean
  submitError: string | null
  onCancelEdit: () => void
  onSubmit: (
    payload: RecordingScheduleInput | RecordingScheduleUpdate,
    isUpdate: boolean,
  ) => void
}) {
  const [state, setState] = useState<ScheduleFormState>(() =>
    editing ? stateFromSchedule(editing) : emptyFormState(),
  )
  // Validation errors surface only after the operator has tried to submit
  // once. Until then the form stays "clean" so we don't yell at a half-typed
  // input.
  const [showErrors, setShowErrors] = useState<boolean>(false)

  const idSlug = useId()
  const idName = useId()
  const idKind = useId()
  const idInput = useId()
  const idUri = useId()
  const idRecKind = useId()
  const idStart = useId()
  const idTime = useId()
  const idDuration = useId()
  const idEncoder = useId()
  const idEncoderList = useId()
  const idLoudness = useId()
  const idTarget = useId()
  const idEnabled = useId()

  // UX-10: when the form switches mode (create ↔ edit), move keyboard focus
  // to the heading and let screen-readers announce the new mode via the
  // `role="status"` live region. The form is keyed on `schedule_id` at the
  // parent, so this component re-mounts when the operator clicks Edit on a
  // different row — meaning the effect fires once per mode change.
  const headingRef = useRef<HTMLHeadingElement | null>(null)
  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  const errors = validateForm(state)
  const hasErrors = Object.keys(errors).length > 0
  const isUpdate = editing != null
  const isLive = (LIVE_SOURCE_KINDS as readonly string[]).includes(state.source_kind)

  const handleSubmit = () => {
    setShowErrors(true)
    if (hasErrors) return
    const durationSeconds = parseDurationHMS(state.duration_text)
    if (durationSeconds == null) return
    const source: RecordingSource = isLive
      ? { kind: state.source_kind, input_id: state.input_id.trim() }
      : { kind: state.source_kind, uri: state.uri.trim() }
    const recurrence: RecurrenceSpec =
      state.recurrence_kind === 'one_shot'
        ? {
            kind: 'one_shot',
            // datetime-local gives "YYYY-MM-DDTHH:MM"; add seconds + Z so the
            // backend's pydantic ISO-8601 parser doesn't trip.
            start: `${state.one_shot_start}:00Z`,
          }
        : {
            kind: 'weekly',
            weekdays: state.weekly_days
              .map((on, i) => (on ? i : -1))
              .filter((i) => i >= 0),
            time_hhmm: state.weekly_time.trim(),
          }
    if (isUpdate && editing) {
      const payload: RecordingScheduleUpdate = {
        name: state.name.trim(),
        source,
        recurrence,
        duration_seconds: durationSeconds,
        encoder_profile: state.encoder_profile.trim(),
        loudness_regime: state.loudness_regime,
        target_series: state.target_series.trim() === '' ? null : state.target_series.trim(),
        enabled: state.enabled,
      }
      onSubmit(payload, true)
    } else {
      const payload: RecordingScheduleInput = {
        schedule_id: state.schedule_id.trim(),
        station_id: DEFAULT_STATION_ID,
        name: state.name.trim(),
        source,
        recurrence,
        duration_seconds: durationSeconds,
        encoder_profile: state.encoder_profile.trim(),
        loudness_regime: state.loudness_regime,
        target_series: state.target_series.trim() === '' ? null : state.target_series.trim(),
        custom_field_values: {},
        enabled: state.enabled,
      }
      onSubmit(payload, false)
    }
  }

  return (
    <section
      aria-label={isUpdate ? 'Edit recording schedule' : 'Create recording schedule'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{
        background: 'var(--cc-surface)',
        border: '1px solid var(--cc-line)',
        // UX-15: subtle brand accent on the form so the operator reads it as
        // the editor for the table above, not a third near-identical card.
        borderLeft: '4px solid var(--cc-brand)',
      }}
    >
      {/* UX-10: live region announces the create/edit mode switch. */}
      <div role="status" aria-live="polite" className="sr-only">
        {isUpdate
          ? `Editing schedule ${editing?.name ?? ''}`
          : 'Creating new schedule'}
      </div>
      <div className="flex items-center justify-between">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="text-sm font-semibold outline-none"
        >
          {isUpdate ? `Edit "${editing?.name}"` : 'New schedule'}
        </h2>
        {isUpdate && (
          <button
            type="button"
            onClick={onCancelEdit}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Cancel edit
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label htmlFor={idSlug} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Schedule ID (slug)</span>
          <input
            id={idSlug}
            type="text"
            value={state.schedule_id}
            disabled={isUpdate}
            placeholder="evening-news"
            onChange={(e) => setState((s) => ({ ...s, schedule_id: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          {showErrors && errors.schedule_id && (
            <span style={{ color: 'var(--cc-warn)' }}>{errors.schedule_id}</span>
          )}
        </label>

        <label htmlFor={idName} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Name</span>
          <input
            id={idName}
            type="text"
            value={state.name}
            placeholder="Evening news"
            onChange={(e) => setState((s) => ({ ...s, name: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          {showErrors && errors.name && (
            <span style={{ color: 'var(--cc-warn)' }}>{errors.name}</span>
          )}
        </label>

        <label htmlFor={idKind} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Source kind</span>
          <select
            id={idKind}
            value={state.source_kind}
            onChange={(e) =>
              setState((s) => ({ ...s, source_kind: e.target.value as RecordingSourceKind }))
            }
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          >
            <optgroup label="Live inputs">
              {LIVE_SOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Network streams">
              {NETWORK_SOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </optgroup>
          </select>
        </label>

        {isLive ? (
          <label htmlFor={idInput} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Input ID</span>
            <input
              id={idInput}
              type="text"
              value={state.input_id}
              placeholder="sdi-1"
              onChange={(e) => setState((s) => ({ ...s, input_id: e.target.value }))}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
          </label>
        ) : (
          <label htmlFor={idUri} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>URI</span>
            <input
              id={idUri}
              type="text"
              value={state.uri}
              placeholder="rtsp://camera.local/stream"
              onChange={(e) => setState((s) => ({ ...s, uri: e.target.value }))}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
          </label>
        )}
        {showErrors && errors.source && (
          <span className="text-xs sm:col-span-2" style={{ color: 'var(--cc-warn)' }}>
            {errors.source}
          </span>
        )}

        <label htmlFor={idRecKind} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Recurrence</span>
          <select
            id={idRecKind}
            value={state.recurrence_kind}
            onChange={(e) =>
              setState((s) => ({
                ...s,
                recurrence_kind: e.target.value as 'one_shot' | 'weekly',
              }))
            }
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          >
            <option value="one_shot">One-shot</option>
            <option value="weekly">Weekly</option>
          </select>
        </label>

        {state.recurrence_kind === 'one_shot' ? (
          <label htmlFor={idStart} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Start (UTC)</span>
            <input
              id={idStart}
              type="datetime-local"
              value={state.one_shot_start}
              onChange={(e) => setState((s) => ({ ...s, one_shot_start: e.target.value }))}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
            {/* UX-2: the browser renders datetime-local in the OPERATOR's
                local zone, but we store + send the value as UTC. Show a
                live local-time echo so the operator can sanity-check what
                wall-clock will fire. */}
            {state.one_shot_start && (
              <span
                data-testid="one-shot-local-echo"
                style={{ color: 'var(--cc-ink-3)' }}
              >
                In your local time: {utcDateTimeLocalToLocalEcho(state.one_shot_start) || '—'}
              </span>
            )}
          </label>
        ) : (
          <div className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Weekdays</span>
            {/* UX-11: presets save 4+ tab/space presses for the common
                weekday / weekend / every-day cases. */}
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                aria-label="Weekly preset: weekdays (Mon-Fri)"
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    weekly_days: [true, true, true, true, true, false, false],
                  }))
                }
                className="rounded-md px-2 py-0.5 text-[11px]"
                style={INPUT_STYLE}
              >
                Weekdays
              </button>
              <button
                type="button"
                aria-label="Weekly preset: weekends (Sat/Sun)"
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    weekly_days: [false, false, false, false, false, true, true],
                  }))
                }
                className="rounded-md px-2 py-0.5 text-[11px]"
                style={INPUT_STYLE}
              >
                Weekend
              </button>
              <button
                type="button"
                aria-label="Weekly preset: every day"
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    weekly_days: [true, true, true, true, true, true, true],
                  }))
                }
                className="rounded-md px-2 py-0.5 text-[11px]"
                style={INPUT_STYLE}
              >
                Every day
              </button>
              <button
                type="button"
                aria-label="Weekly preset: clear all days"
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    weekly_days: [false, false, false, false, false, false, false],
                  }))
                }
                className="rounded-md px-2 py-0.5 text-[11px]"
                style={INPUT_STYLE}
              >
                Clear
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {WEEKDAY_LABELS.map((label, i) => (
                <label key={label} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    aria-label={`Weekly day ${label}`}
                    checked={state.weekly_days[i]}
                    onChange={(e) =>
                      setState((s) => {
                        const next = [...s.weekly_days]
                        next[i] = e.target.checked
                        return { ...s, weekly_days: next }
                      })
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            <label htmlFor={idTime} className="grid gap-1 text-xs">
              <span style={{ color: 'var(--cc-ink-3)' }}>Time (HH:MM UTC)</span>
              <input
                id={idTime}
                type="text"
                value={state.weekly_time}
                placeholder="19:00"
                onChange={(e) => setState((s) => ({ ...s, weekly_time: e.target.value }))}
                className="rounded-md px-2 py-1.5"
                style={INPUT_STYLE}
              />
              {/* UX-2: live local-time echo of the typed UTC time. */}
              {state.weekly_time && (
                <span
                  data-testid="weekly-time-local-echo"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  In your local time: {utcHHMMToLocalEcho(state.weekly_time) || '—'}
                </span>
              )}
            </label>
          </div>
        )}
        {/* UX-8: next-3 fire previews so the operator confirms "yes this
            fires the day before the meeting at noon my time" before
            saving. We compute from the currently-typed form state (not the
            saved schedule) so it updates live. */}
        {(() => {
          const previews =
            state.recurrence_kind === 'one_shot'
              ? nextOneShotFireTimes(state.one_shot_start)
              : nextWeeklyFireTimes(
                  state.weekly_days
                    .map((on, i) => (on ? i : -1))
                    .filter((i) => i >= 0),
                  state.weekly_time,
                  3,
                )
          if (previews.length === 0) return null
          return (
            <div
              data-testid="next-fire-preview"
              className="text-xs sm:col-span-2"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              <div className="font-semibold">
                Next {previews.length === 1 ? 'fire' : `${previews.length} fires`}:
              </div>
              <ul className="ml-4 list-disc">
                {previews.map((d) => (
                  <li key={d.toISOString()}>{formatFirePreview(d)}</li>
                ))}
              </ul>
            </div>
          )
        })()}
        {showErrors && errors.recurrence && (
          <span className="text-xs sm:col-span-2" style={{ color: 'var(--cc-warn)' }}>
            {errors.recurrence}
          </span>
        )}

        <label htmlFor={idDuration} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Duration (HH:MM:SS)</span>
          <input
            id={idDuration}
            type="text"
            value={state.duration_text}
            placeholder="01:30:00"
            onChange={(e) => setState((s) => ({ ...s, duration_text: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          {showErrors && errors.duration && (
            <span style={{ color: 'var(--cc-warn)' }}>{errors.duration}</span>
          )}
        </label>

        {/* UX-12: rename to operator-vocabulary "Quality preset" but keep
            encoder_profile as the API field name.
            UX-3: <datalist> seeds autocomplete with the engine-shipped slugs
            so the operator doesn't have to memorize them. The seam comment
            on ENCODER_PROFILE_SUGGESTIONS notes how to swap in a live admin
            endpoint when one ships. */}
        <label htmlFor={idEncoder} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Quality preset (encoder profile)</span>
          <input
            id={idEncoder}
            type="text"
            list={idEncoderList}
            value={state.encoder_profile}
            onChange={(e) => setState((s) => ({ ...s, encoder_profile: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          <datalist id={idEncoderList}>
            {ENCODER_PROFILE_SUGGESTIONS.map((slug) => (
              <option key={slug} value={slug} />
            ))}
          </datalist>
          <span className="text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            Common values: hw-h264-1080p, hw-h264-720p. Contact your station
            admin for the full list of available presets.
          </span>
          {showErrors && errors.encoder_profile && (
            <span style={{ color: 'var(--cc-warn)' }}>{errors.encoder_profile}</span>
          )}
        </label>

        <label htmlFor={idLoudness} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Loudness regime</span>
          <select
            id={idLoudness}
            value={state.loudness_regime}
            onChange={(e) => setState((s) => ({ ...s, loudness_regime: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          >
            {LOUDNESS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {/* UX-4: inline help — operators know their delivery channel,
              not the LUFS target. */}
          <span
            data-testid="loudness-help"
            className="text-[11px]"
            style={{ color: 'var(--cc-ink-3)' }}
          >
            {LOUDNESS_HELP[state.loudness_regime] ?? ''}
          </span>
        </label>

        <label htmlFor={idTarget} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Target series (optional)</span>
          <input
            id={idTarget}
            type="text"
            value={state.target_series}
            onChange={(e) => setState((s) => ({ ...s, target_series: e.target.value }))}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>

        <label htmlFor={idEnabled} className="flex items-center gap-2 text-xs">
          <input
            id={idEnabled}
            type="checkbox"
            checked={state.enabled}
            onChange={(e) => setState((s) => ({ ...s, enabled: e.target.checked }))}
          />
          <span>Enabled</span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          aria-label={isUpdate ? 'Save schedule changes' : 'Create schedule'}
          disabled={submitting}
          onClick={handleSubmit}
          className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {submitting
            ? isUpdate
              ? 'Saving…'
              : 'Creating…'
            : isUpdate
              ? 'Save changes'
              : 'Create schedule'}
        </button>
      </div>

      {submitError && <Banner tone="warn">{submitError}</Banner>}
    </section>
  )
}

// --- Jobs table -------------------------------------------------------------

function JobsSection({
  jobs,
  isLoading,
  isFetching,
  loadError,
  filter,
  canWrite,
  anyActive,
  autoRefreshPaused,
  lastRefreshedAt,
  stoppingId,
  confirmStopJobId,
  onFilterChange,
  onRefresh,
  onToggleAutoRefresh,
  onArmStop,
  onCancelStop,
  onConfirmStop,
}: {
  jobs: RecordingJob[]
  isLoading: boolean
  isFetching: boolean
  loadError: string | null
  filter: JobsFilterState
  canWrite: boolean
  anyActive: boolean
  autoRefreshPaused: boolean
  lastRefreshedAt: Date | null
  stoppingId: string | null
  confirmStopJobId: string | null
  onFilterChange: (next: JobsFilterState) => void
  onRefresh: () => void
  onToggleAutoRefresh: () => void
  onArmStop: (id: string) => void
  onCancelStop: () => void
  onConfirmStop: (id: string) => void
}) {
  const idState = useId()
  const idSchedule = useId()
  const idLimit = useId()

  return (
    <section
      // UX-13: "Recordings" matches operator vocabulary; engine-speak "jobs"
      // is left only in the internal `RecordingJob` type names.
      aria-label="Recordings"
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Recordings</h2>
          {/* UX-6: visible auto-refresh state + Pause/Resume control + a
              "last refreshed at" timestamp when paused so the operator
              knows how stale the data is. */}
          {anyActive && (
            <span
              data-testid="autorefresh-pill"
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
              style={{
                background: autoRefreshPaused
                  ? 'var(--cc-warn-soft)'
                  : 'var(--cc-ok-soft)',
                border: `1px solid ${
                  autoRefreshPaused ? 'var(--cc-warn)' : 'var(--cc-ok)'
                }`,
                color: autoRefreshPaused ? 'var(--cc-warn)' : 'var(--cc-ok)',
              }}
            >
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{
                  background: autoRefreshPaused
                    ? 'var(--cc-warn)'
                    : 'var(--cc-ok)',
                }}
              />
              {autoRefreshPaused
                ? `Paused${
                    lastRefreshedAt
                      ? ` · last refresh ${lastRefreshedAt.toLocaleTimeString()}`
                      : ''
                  }`
                : 'Live · refreshing every 5 s'}
              <button
                type="button"
                aria-label={
                  autoRefreshPaused ? 'Resume auto-refresh' : 'Pause auto-refresh'
                }
                onClick={onToggleAutoRefresh}
                className="ml-1 underline"
              >
                {autoRefreshPaused ? 'Resume' : 'Pause'}
              </button>
            </span>
          )}
        </div>
        <button
          type="button"
          aria-label="Refresh recordings"
          onClick={onRefresh}
          // UX-16: busy state + disabled while a refetch is in flight so
          // the operator can't queue multiple Refresh clicks.
          disabled={isFetching}
          className="rounded-md px-2 py-1 text-xs font-medium disabled:opacity-50"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label htmlFor={idState} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>State</span>
          <select
            id={idState}
            value={filter.state}
            onChange={(e) =>
              onFilterChange({
                ...filter,
                state: e.target.value === '' ? '' : (e.target.value as RecordingJobState),
              })
            }
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          >
            <option value="">All states</option>
            <option value="scheduled">scheduled</option>
            <option value="arming">arming</option>
            <option value="recording">recording</option>
            <option value="finalizing">finalizing</option>
            <option value="done">done</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
        </label>
        <label htmlFor={idSchedule} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Schedule ID</span>
          <input
            id={idSchedule}
            type="text"
            value={filter.schedule_id}
            placeholder="any"
            onChange={(e) => onFilterChange({ ...filter, schedule_id: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
        <label htmlFor={idLimit} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Limit</span>
          <input
            id={idLimit}
            type="number"
            min={1}
            max={500}
            value={filter.limit}
            onChange={(e) =>
              onFilterChange({ ...filter, limit: Number(e.target.value) || 50 })
            }
            className="w-20 rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
      </div>

      {loadError && <Banner tone="warn">{loadError}</Banner>}

      {isLoading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading recordings…
        </p>
      ) : jobs.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No recordings yet — schedule a recording or use Record Now.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            {/* UX-17: screen-reader caption for table-navigation mode. */}
            <caption className="sr-only">Recordings</caption>
            <thead>
              <tr style={{ color: 'var(--cc-ink-3)' }}>
                <th className="py-1 pr-3 font-semibold">Planned start</th>
                <th className="py-1 pr-3 font-semibold">Source</th>
                <th className="py-1 pr-3 font-semibold">State</th>
                <th className="py-1 pr-3 font-semibold">Duration</th>
                <th className="py-1 pr-3 font-semibold">Bytes</th>
                <th className="py-1 pr-3 font-semibold">Asset</th>
                <th className="py-1 pr-3 font-semibold">Failure</th>
                {canWrite && <th className="py-1 pr-3 font-semibold">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const canStop = ACTIVE_JOB_STATES.has(j.state)
                const isConfirmingStop = confirmStopJobId === j.job_id
                return (
                  <tr key={j.job_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
                    <td className="py-1.5 pr-3">{formatPlannedStart(j.planned_start)}</td>
                    <td className="py-1.5 pr-3">{humanizeSource(j.source_snapshot)}</td>
                    <td className="py-1.5 pr-3">
                      <StateBadge state={j.state} />
                    </td>
                    <td className="py-1.5 pr-3">{jobDuration(j)}</td>
                    <td className="py-1.5 pr-3">{humanizeBytes(j.bytes_written)}</td>
                    <td className="py-1.5 pr-3">
                      {j.asset_id ? (
                        // UX-18: title attribute exposes the full asset id
                        // even when truncated, and the small arrow is a
                        // standard "this opens details" affordance.
                        <a
                          href={`#/assets/${encodeURIComponent(j.asset_id)}`}
                          title={j.asset_id}
                          className="underline"
                          style={{ color: 'var(--cc-info)' }}
                        >
                          {j.asset_id}
                          <span aria-hidden="true"> →</span>
                        </a>
                      ) : (
                        <span style={{ color: 'var(--cc-ink-3)' }}>—</span>
                      )}
                    </td>
                    {/* UX-7: failure_reason is the most important data on
                        a failed row — use error ink at full contrast, not
                        a low-grey. */}
                    <td
                      className="py-1.5 pr-3"
                      style={{
                        color:
                          j.state === 'failed' && j.failure_reason
                            ? 'var(--cc-err)'
                            : 'var(--cc-ink)',
                        fontWeight:
                          j.state === 'failed' && j.failure_reason ? 600 : 400,
                      }}
                    >
                      {j.failure_reason ?? ''}
                    </td>
                    {canWrite && (
                      <td className="py-1.5 pr-3">
                        {canStop &&
                          (isConfirmingStop ? (
                            <div className="flex flex-wrap items-center gap-1">
                              {/* UX-1: 2-step Stop confirm. The first click
                                  arms; the second click actually stops the
                                  recording. Mirrors the Delete pattern in
                                  SchedulesSection so a misclick mid-meeting
                                  can't kill a 2-hour council recording. */}
                              <button
                                type="button"
                                aria-label={`Confirm stop job ${j.job_id}`}
                                disabled={stoppingId === j.job_id}
                                onClick={() => onConfirmStop(j.job_id)}
                                className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
                                style={{
                                  background: 'var(--cc-err-soft)',
                                  border: '1px solid var(--cc-err)',
                                }}
                              >
                                {stoppingId === j.job_id
                                  ? 'Stopping…'
                                  : 'Confirm stop'}
                              </button>
                              <button
                                type="button"
                                aria-label={`Cancel stop job ${j.job_id}`}
                                onClick={onCancelStop}
                                className="rounded-md px-2 py-1 text-xs font-medium"
                                style={{
                                  background: 'var(--cc-surface)',
                                  border: '1px solid var(--cc-line)',
                                }}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              aria-label={`Stop job ${j.job_id}`}
                              disabled={stoppingId === j.job_id}
                              onClick={() => onArmStop(j.job_id)}
                              className="rounded-md px-2 py-1 text-xs font-medium disabled:opacity-50"
                              style={{
                                background: 'var(--cc-warn-soft)',
                                border: '1px solid var(--cc-warn)',
                              }}
                            >
                              Stop
                            </button>
                          ))}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
