// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator console: Setup > Cable Commissioning (S3). Screens 8-11 of the
// canonical 11-screen wizard (S3 §1a) -- first-run cable checks, channel
// output setup, output proof, and the final commissioning report. Rendered
// as 4 sequentially-gated sections keyed off server state
// (GET .../commissioning/state), matching this codebase's existing
// SetupScreen idiom (derived boolean gates from React Query data, not a
// synthetic in-memory step index) -- a restart mid-commissioning resumes
// exactly where the server's state left off.
//
// Roles (S3 §4): write/orchestration endpoints require setup_admin;
// read-only state requires setup_admin OR support_admin.

import { type ReactNode, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'
import {
  ApiError,
  buildCommissioningReport,
  getCommissioningState,
  getStaffIdentity,
  listChannelProfiles,
  listHeadendProfiles,
  runCommissioningChecks,
  runCommissioningOutputProof,
  saveChannelCommissioningSetup,
} from '../api/client'
import type {
  ChannelCommissioningSetup,
  CommissioningCheckItem,
  CommissioningState,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import { SupportBundlePanel } from './SystemHealthScreen'

const READ_ROLES = ['setup_admin', 'support_admin']
const WRITE_ROLES = ['setup_admin']

type Tone = 'neutral' | 'ok' | 'warn' | 'info' | 'red'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  red: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div role="alert" className="rounded-md p-3 text-sm" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

function statusTone(status: CommissioningCheckItem['status']): Tone {
  if (status === 'pass') return 'ok'
  if (status === 'fail') return 'red'
  if (status === 'warning') return 'warn'
  return 'neutral'
}

function CheckRow({ item }: { item: CommissioningCheckItem }) {
  const c = TONE_COLORS[statusTone(item.status)]
  return (
    <li className="flex flex-col gap-0.5 rounded-md p-2 text-xs" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold">{item.label}</span>
        <span className="uppercase" style={{ color: 'var(--cc-ink-3)' }}>{item.status}</span>
      </div>
      {item.detail && <span>{item.detail}</span>}
      {item.next_step && <span style={{ color: 'var(--cc-ink-3)' }}>Next step: {item.next_step}</span>}
    </li>
  )
}

function StepCard({
  step,
  title,
  locked,
  lockedMessage,
  children,
}: {
  step: number
  title: string
  locked?: boolean
  lockedMessage?: string
  children: ReactNode
}) {
  return (
    <section
      aria-label={`Screen ${step}: ${title}`}
      className="space-y-3 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">
        Screen {step}: {title}
      </h2>
      {locked ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {lockedMessage ?? 'Complete the previous step first.'}
        </p>
      ) : (
        children
      )}
    </section>
  )
}

function FirstRunChecksStep({ canWrite, onComplete }: { canWrite: boolean; onComplete: () => void }) {
  const [stationName, setStationName] = useState('')
  const runMut = useMutation({
    mutationFn: () =>
      runCommissioningChecks({ deployment_profile: 'peg-cable', station_name: stationName }),
    onSuccess: onComplete,
  })

  return (
    <StepCard step={8} title="First-run cable checks">
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Station name</span>
          <input
            aria-label="Station name for commissioning report"
            value={stationName}
            onChange={(e) => setStationName(e.target.value)}
            disabled={!canWrite || runMut.isPending}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <button
          type="button"
          disabled={!canWrite || runMut.isPending}
          onClick={() => runMut.mutate()}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          {runMut.isPending ? 'Running checks…' : 'Run cable checks'}
        </button>
      </div>
      {runMut.isError && <Banner tone="warn">{apiMessage(runMut.error, 'Could not run the cable checks.')}</Banner>}
      {runMut.data && (
        <>
          <Banner tone={runMut.data.ready ? 'ok' : 'red'}>
            {runMut.data.ready ? 'Ready to continue.' : 'Not ready -- fix the failing checks below.'}
          </Banner>
          <ul className="space-y-1">
            {(runMut.data.checks ?? []).map((item) => (
              <CheckRow key={item.id} item={item} />
            ))}
          </ul>
        </>
      )}
    </StepCard>
  )
}

const OUTPUT_FORMATS: ChannelCommissioningSetup['output_format'][] = [
  '720p30',
  '1080i60',
  '1080p30',
  'SD480i60',
]

function ChannelSetupStep({
  canWrite,
  locked,
  onComplete,
}: {
  canWrite: boolean
  locked: boolean
  onComplete: () => void
}) {
  const [channelId, setChannelId] = useState('')
  const [channelName, setChannelName] = useState('')
  const [outputFormat, setOutputFormat] = useState<ChannelCommissioningSetup['output_format']>('1080p30')
  const [headendProfileId, setHeadendProfileId] = useState('')
  const [destination, setDestination] = useState('')
  const [sdiDevice, setSdiDevice] = useState('')
  const [fillPolicy, setFillPolicy] = useState<ChannelCommissioningSetup['fill_policy']>('slate')
  const [cea708, setCea708] = useState(false)

  const channelsQuery = useQuery({ queryKey: ['channel-profiles'], queryFn: listChannelProfiles, enabled: !locked })
  const profilesQuery = useQuery({ queryKey: ['headend-profiles'], queryFn: listHeadendProfiles, enabled: !locked })

  const saveMut = useMutation({
    mutationFn: () =>
      saveChannelCommissioningSetup({
        channel_id: channelId,
        channel_name: channelName || channelId,
        output_format: outputFormat,
        headend_profile_id: headendProfileId,
        destination,
        sdi_device: sdiDevice || null,
        fill_policy: fillPolicy,
        cea708_passthrough: cea708,
      }),
    onSuccess: onComplete,
  })

  const canSave =
    canWrite && !saveMut.isPending && channelId.trim() !== '' && headendProfileId.trim() !== '' && destination.trim() !== ''

  return (
    <StepCard step={9} title="Channel output setup" locked={locked} lockedMessage="Complete the first-run cable checks first (all pass or Continue-anyway on warnings).">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Channel</span>
          <select
            aria-label="Channel"
            value={channelId}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => {
              setChannelId(e.target.value)
              const found = channelsQuery.data?.find((c) => c.channel_id === e.target.value)
              if (found) setChannelName(found.branding.display_name ?? found.channel_id)
            }}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="">Choose a channel…</option>
            {(channelsQuery.data ?? []).map((c) => (
              <option key={c.channel_id} value={c.channel_id}>
                {c.branding.display_name ?? c.channel_id}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Output format</span>
          <select
            aria-label="Output format"
            value={outputFormat}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => setOutputFormat(e.target.value as ChannelCommissioningSetup['output_format'])}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            {OUTPUT_FORMATS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Headend profile</span>
          <select
            aria-label="Headend profile"
            value={headendProfileId}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => setHeadendProfileId(e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="">Choose a headend profile…</option>
            {(profilesQuery.data ?? []).map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Destination address:port</span>
          <input
            aria-label="Destination address and port"
            value={destination}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => setDestination(e.target.value)}
            placeholder="192.168.1.100:5000"
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>SDI device (optional)</span>
          <input
            aria-label="SDI device"
            value={sdiDevice}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => setSdiDevice(e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Fill policy</span>
          <select
            aria-label="Fill policy"
            value={fillPolicy}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => setFillPolicy(e.target.value as ChannelCommissioningSetup['fill_policy'])}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="slate">Slate</option>
            <option value="loop">Loop</option>
            <option value="silence">Silence</option>
          </select>
        </label>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={cea708}
          disabled={!canWrite || saveMut.isPending}
          onChange={(e) => setCea708(e.target.checked)}
        />
        <span>CEA-708 caption passthrough (verified in the output proof below when enabled)</span>
      </label>
      {saveMut.isError && <Banner tone="warn">{apiMessage(saveMut.error, 'Could not save the channel setup.')}</Banner>}
      {saveMut.isSuccess && <Banner tone="ok">Channel setup saved.</Banner>}
      <div className="flex justify-end">
        <button
          type="button"
          disabled={!canSave}
          onClick={() => saveMut.mutate()}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          {saveMut.isPending ? 'Saving…' : 'Save and continue'}
        </button>
      </div>
    </StepCard>
  )
}

function OutputProofStep({
  canWrite,
  locked,
  channelId,
  onComplete,
}: {
  canWrite: boolean
  locked: boolean
  channelId: string | null
  onComplete: () => void
}) {
  const [pattern, setPattern] = useState<'bars' | 'live' | 'slate'>('bars')
  const [durationSeconds, setDurationSeconds] = useState(60)

  const runMut = useMutation({
    mutationFn: () =>
      runCommissioningOutputProof({
        channel_id: channelId ?? '',
        test_pattern: pattern,
        duration_seconds: durationSeconds,
      }),
    onSuccess: onComplete,
  })

  return (
    <StepCard
      step={10}
      title="Output proof"
      locked={locked}
      lockedMessage="Save the channel output setup first."
    >
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Generating test {pattern} on channel {channelId} through the GStreamer engine, verified
        with a concurrent TSDuck probe. This call blocks for the full duration.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Test pattern</span>
          <select
            aria-label="Test pattern"
            value={pattern}
            disabled={!canWrite || runMut.isPending}
            onChange={(e) => setPattern(e.target.value as 'bars' | 'live' | 'slate')}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="bars">Bars + tone</option>
            <option value="live">Live</option>
            <option value="slate">Slate</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Duration (seconds)</span>
          <input
            aria-label="Proof duration in seconds"
            type="number"
            min={1}
            max={1800}
            value={durationSeconds}
            disabled={!canWrite || runMut.isPending}
            onChange={(e) => setDurationSeconds(Number(e.target.value) || 60)}
            className="w-24 rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <button
          type="button"
          disabled={!canWrite || runMut.isPending || !channelId}
          onClick={() => runMut.mutate()}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          {runMut.isPending ? 'Running proof…' : 'Start proof run'}
        </button>
      </div>
      {runMut.isError && <Banner tone="warn">{apiMessage(runMut.error, 'The output proof failed to start.')}</Banner>}
      {runMut.data && (
        <div className="space-y-1 text-xs">
          <Banner tone={runMut.data.verdict === 'pass' ? 'ok' : runMut.data.verdict === 'partial' ? 'warn' : 'red'}>
            Verdict: {runMut.data.verdict}
          </Banner>
          {runMut.data.detail && <p>{runMut.data.detail}</p>}
          {(runMut.data.blockers ?? []).map((b) => (
            <p key={b} style={{ color: 'var(--cc-warn)' }}>
              {b}
            </p>
          ))}
          {(runMut.data.not_claimed ?? []).map((line) => (
            <p key={line} style={{ color: 'var(--cc-ink-3)' }}>
              (boundary) {line}
            </p>
          ))}
        </div>
      )}
    </StepCard>
  )
}

function CommissioningReportStep({
  canWrite,
  locked,
  state,
}: {
  canWrite: boolean
  locked: boolean
  state: CommissioningState | undefined
}) {
  const [stationName, setStationName] = useState('')
  const reportMut = useMutation({ mutationFn: () => buildCommissioningReport(stationName) })
  const report = reportMut.data ?? state?.report ?? null

  return (
    <StepCard step={11} title="Commissioning report" locked={locked} lockedMessage="Run the output proof first.">
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Station name</span>
          <input
            aria-label="Station name for the report"
            value={stationName}
            disabled={!canWrite || reportMut.isPending}
            onChange={(e) => setStationName(e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <button
          type="button"
          disabled={!canWrite || reportMut.isPending}
          onClick={() => reportMut.mutate()}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          {reportMut.isPending ? 'Building report…' : 'Generate report'}
        </button>
      </div>
      {reportMut.isError && <Banner tone="warn">{apiMessage(reportMut.error, 'Could not build the commissioning report.')}</Banner>}
      {report && (
        <div className="space-y-2 text-xs">
          <Banner tone={report.ready_for_broadcast ? 'ok' : 'red'}>
            {report.ready_for_broadcast ? 'Ready for broadcast' : 'Commissioning incomplete'}
          </Banner>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt style={{ color: 'var(--cc-ink-3)' }}>Channel</dt>
            <dd>{report.channel_name}</dd>
            <dt style={{ color: 'var(--cc-ink-3)' }}>Headend profile</dt>
            <dd>{report.headend_profile_id}</dd>
            <dt style={{ color: 'var(--cc-ink-3)' }}>Output format</dt>
            <dd>{report.output_format}</dd>
          </dl>
          {(report.next_steps ?? []).length > 0 && (
            <div>
              <h3 className="font-semibold" style={{ color: 'var(--cc-ink-3)' }}>
                Next steps
              </h3>
              <ul className="list-disc pl-4">
                {(report.next_steps ?? []).map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      <SupportBundlePanel canCreate={canWrite} />
    </StepCard>
  )
}

export function CommissioningWizardScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, READ_ROLES)
  const canWrite = hasRole(identityQuery.data, WRITE_ROLES)

  const stateQuery = useQuery<CommissioningState>({
    queryKey: ['commissioning-state'],
    queryFn: getCommissioningState,
    enabled: canRead,
  })

  function refetchState() {
    qc.invalidateQueries({ queryKey: ['commissioning-state'] })
  }

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
        <AuthRequiredState error={identityQuery.error} />
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Cable Commissioning requires the setup admin or support admin role. Ask your station
          admin for access.
        </Banner>
      </div>
    )
  }

  const checksReady = stateQuery.data?.first_run_checks?.ready === true
  const channelSetup = stateQuery.data?.channel_setup ?? null
  const proofRun = stateQuery.data?.proof_run ?? null

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Cable Commissioning</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Screens 8-11 of the commissioning wizard (S3): first-run cable checks, channel output
          setup, output proof, and the final report. Progress is saved after each step, so
          leaving and returning resumes where you left off.
        </p>
      </div>

      {stateQuery.isLoading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading commissioning progress…
        </p>
      ) : stateQuery.isError ? (
        <Banner tone="warn">{apiMessage(stateQuery.error, 'Could not load commissioning progress.')}</Banner>
      ) : (
        <div className="space-y-3">
          <FirstRunChecksStep canWrite={canWrite} onComplete={refetchState} />
          <ChannelSetupStep canWrite={canWrite} locked={!checksReady} onComplete={refetchState} />
          <OutputProofStep
            canWrite={canWrite}
            locked={channelSetup == null}
            channelId={channelSetup?.channel_id ?? null}
            onComplete={refetchState}
          />
          <CommissioningReportStep canWrite={canWrite} locked={proofRun == null} state={stateQuery.data} />
        </div>
      )}
    </div>
  )
}
