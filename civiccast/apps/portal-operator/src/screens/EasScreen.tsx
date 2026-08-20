// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator console for public-safety (EAS) ingest + display (S11c). Lists configured
// CAP sources and active alerts, and lets a privileged operator display an alert on a
// channel as a crawl / overlay / (operator-confirmed) forced slate.
// CivicCast is never an EAS device; the posture banner states that permanently, a forced
// slate always requires per-alert confirmation, and no public string claims EAS compliance.

import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'

import {
  ApiError,
  clearEasDecision,
  displayEasAlert,
  getStaffIdentity,
  listChannelProfiles,
  listEasAlerts,
  listEasDecisions,
  listEasSources,
} from '../api/client'
import type {
  EasCapAlert,
  EasCapSource,
  EasDisplayDecision,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import { EasPostureBanner } from '../components/EasPostureBanner'

const READ_ROLES = ['setup_admin', 'support_admin', 'meeting_operator']
const DISPLAY_ROLES = ['setup_admin', 'meeting_operator']

type Tone = 'err' | 'warn' | 'info' | 'ok'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  err: { bg: 'var(--cc-err-soft)', bd: 'var(--cc-err)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
}

const SEVERITY_TONE: Record<string, Tone> = {
  extreme: 'err',
  severe: 'warn',
  moderate: 'info',
  minor: 'info',
  unknown: 'ok',
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

// role="alert" — an assertive live region. Reserved for genuine error/notice banners.
function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div role="alert" className="rounded-md p-3 text-sm" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

// A plain inline label (NOT a live region) — a list of these must not interrupt a
// screen reader on every render.
function SeverityBadge({ severity }: { severity: string }) {
  const c = TONE_COLORS[SEVERITY_TONE[severity] ?? 'info']
  return (
    <span
      className="rounded px-1.5 py-0.5 text-xs font-semibold"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {severity}
    </span>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
      {label}
    </p>
  )
}

export function SourcesSection({ sources, loading = false }: { sources: EasCapSource[]; loading?: boolean }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Alert sources</h2>
      {loading ? (
        <Loading label="Loading sources…" />
      ) : sources.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No alert sources are configured yet. Add an NWS, AMBER, or IPAWS (COG) feed to begin
          ingesting public-safety alerts.
        </p>
      ) : (
        <ul className="space-y-1">
          {sources.map((source) => (
            <li
              key={source.source_id}
              className="flex items-center justify-between gap-3 rounded-md p-2 text-sm"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              <span>
                <strong>{source.label}</strong>{' '}
                <span style={{ color: 'var(--cc-ink-3)' }}>
                  ({source.kind} · ≥ {source.severity_floor ?? 'severe'})
                </span>
              </span>
              <span className="text-xs" style={{ color: source.enabled ? 'var(--cc-ok)' : 'var(--cc-ink-3)' }}>
                {source.enabled ? 'polling' : 'disabled'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

type DisplayMode = 'crawl' | 'overlay' | 'forced_slate'

// One alert row. The forced-slate confirmation is PER ROW (its own state), so arming a
// full-screen takeover on one alert can never enable it on another.
function AlertRow({
  alert,
  canDisplay,
  channelId,
  onDisplay,
}: {
  alert: EasCapAlert
  canDisplay: boolean
  channelId: string
  onDisplay: (alertId: string, mode: DisplayMode, confirmed: boolean) => void
}) {
  const [confirmSlate, setConfirmSlate] = useState(false)
  return (
    <li
      className="space-y-1 rounded-md p-2 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <strong>{alert.event}</strong>
        <SeverityBadge severity={alert.severity} />
      </div>
      {alert.headline && <div style={{ color: 'var(--cc-ink-2)' }}>{alert.headline}</div>}
      {alert.areas && alert.areas.length > 0 && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Areas: {alert.areas.join(', ')}
        </div>
      )}
      {canDisplay && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            className="rounded-md px-2 py-1 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            onClick={() => onDisplay(alert.alert_id, 'crawl', false)}
          >
            Show crawl on {channelId}
          </button>
          <button
            type="button"
            className="rounded-md px-2 py-1 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            onClick={() => onDisplay(alert.alert_id, 'overlay', false)}
          >
            Show overlay
          </button>
          <label className="flex items-center gap-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            <input
              type="checkbox"
              checked={confirmSlate}
              onChange={(e) => setConfirmSlate(e.target.checked)}
            />
            Confirm full-screen takeover
          </label>
          <button
            type="button"
            disabled={!confirmSlate}
            className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            onClick={() => {
              onDisplay(alert.alert_id, 'forced_slate', confirmSlate)
              setConfirmSlate(false) // single-use: re-arm required for the next takeover
            }}
          >
            Forced slate
          </button>
        </div>
      )}
    </li>
  )
}

export function AlertsSection({
  alerts,
  canDisplay,
  channelId,
  onDisplay,
  loading = false,
}: {
  alerts: EasCapAlert[]
  canDisplay: boolean
  channelId: string
  onDisplay: (alertId: string, mode: DisplayMode, confirmed: boolean) => void
  loading?: boolean
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">Active alerts</h2>
      {loading ? (
        <Loading label="Loading alerts…" />
      ) : alerts.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No active alerts.
        </p>
      ) : (
        <ul className="space-y-2">
          {alerts.map((alert) => (
            <AlertRow
              key={alert.alert_id}
              alert={alert}
              canDisplay={canDisplay}
              channelId={channelId}
              onDisplay={onDisplay}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

export function DecisionsSection({
  decisions,
  canDisplay,
  onClear,
  loading = false,
}: {
  decisions: EasDisplayDecision[]
  canDisplay: boolean
  onClear: (decisionId: string) => void
  loading?: boolean
}) {
  const live = decisions.filter((d) => d.state === 'displayed')
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">On-channel now</h2>
      {loading ? (
        <Loading label="Loading…" />
      ) : live.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Nothing is being displayed.
        </p>
      ) : (
        <ul className="space-y-1">
          {live.map((decision) => (
            <li
              key={decision.decision_id}
              className="flex items-center justify-between gap-3 rounded-md p-2 text-sm"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              <span>
                <strong>{decision.channel_id}</strong>{' '}
                <span style={{ color: 'var(--cc-ink-3)' }}>{decision.mode}</span>
              </span>
              {canDisplay && (
                <button
                  type="button"
                  className="rounded-md px-2 py-1 text-xs font-semibold"
                  style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
                  onClick={() => onClear(decision.decision_id)}
                >
                  Clear
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function EasScreen() {
  const qc = useQueryClient()
  const [channelId, setChannelId] = useState('gov')
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, READ_ROLES)
  const canDisplay = hasRole(identityQuery.data, DISPLAY_ROLES)

  const channelsQuery = useQuery({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    enabled: canRead,
  })
  const channels = channelsQuery.data ?? []
  const sourcesQuery = useQuery({ queryKey: ['eas-sources'], queryFn: listEasSources, enabled: canRead })
  const alertsQuery = useQuery({
    queryKey: ['eas-alerts'],
    queryFn: () => listEasAlerts({ active: true }),
    enabled: canRead,
  })
  const decisionsQuery = useQuery({
    queryKey: ['eas-decisions', channelId],
    queryFn: () => listEasDecisions(channelId),
    enabled: canRead,
  })

  const displayMut = useMutation({
    mutationFn: (v: { alertId: string; mode: DisplayMode; confirmed: boolean }) =>
      displayEasAlert(v.alertId, { channel_id: channelId, mode: v.mode, operator_confirmed: v.confirmed }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eas-decisions', channelId] }),
  })
  const clearMut = useMutation({
    mutationFn: (decisionId: string) => clearEasDecision(decisionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eas-decisions', channelId] }),
  })

  if (identityQuery.isLoading) {
    return <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
  }
  if (identityQuery.isError) {
    // An auth/connectivity failure is NOT a permissions problem — say so distinctly.
    return (
      <div className="px-6 py-10 space-y-3">
        <EasPostureBanner />
        <AuthRequiredState error={identityQuery.error} />
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10 space-y-3">
        <EasPostureBanner />
        <Banner tone="info">
          The Emergency Alerts console requires the setup admin, support admin, or meeting operator
          role. Ask your station admin for access.
        </Banner>
      </div>
    )
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Emergency Alerts</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Ingest and display CAP/IPAWS, NWS, and AMBER public-safety alerts on your channels.
        </p>
      </div>

      <EasPostureBanner />

      {displayMut.isError && <Banner tone="err">{apiMessage(displayMut.error, 'Could not display the alert.')}</Banner>}

      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="eas-channel" style={{ color: 'var(--cc-ink-2)' }}>
          Channel
        </label>
        {channels.length > 0 ? (
          <select
            id="eas-channel"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="rounded-md px-2 py-1 text-sm"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            {!channels.some((c) => c.channel_id === channelId) && (
              <option value={channelId}>{channelId}</option>
            )}
            {channels.map((c) => (
              <option key={c.channel_id} value={c.channel_id}>
                {c.channel_id}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="eas-channel"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="rounded-md px-2 py-1 text-sm"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          />
        )}
        {!canDisplay && (
          <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            (read-only — displaying alerts requires the meeting operator or setup admin role)
          </span>
        )}
      </div>

      {sourcesQuery.isError ? (
        <Banner tone="err">{apiMessage(sourcesQuery.error, 'Could not load sources.')}</Banner>
      ) : (
        <SourcesSection sources={sourcesQuery.data ?? []} loading={sourcesQuery.isLoading} />
      )}

      {alertsQuery.isError ? (
        <Banner tone="err">{apiMessage(alertsQuery.error, 'Could not load alerts.')}</Banner>
      ) : (
        <AlertsSection
          alerts={alertsQuery.data ?? []}
          canDisplay={canDisplay}
          channelId={channelId}
          onDisplay={(alertId, mode, confirmed) => displayMut.mutate({ alertId, mode, confirmed })}
          loading={alertsQuery.isLoading}
        />
      )}

      <DecisionsSection
        decisions={decisionsQuery.data ?? []}
        canDisplay={canDisplay}
        onClear={(decisionId) => clearMut.mutate(decisionId)}
        loading={decisionsQuery.isLoading}
      />
    </div>
  )
}
