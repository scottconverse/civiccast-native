// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type {
  ControlRoomReadinessCheck,
  ControlRoomReadinessReport,
} from '../types/api.generated'
import { Link } from 'react-router'
import {
  READINESS_CHECK_BEFORE_MEETING,
  READINESS_DO_NOT_BROADCAST_YET,
  READINESS_READY,
  readinessLabel,
  stateLabel,
  toneForReadiness,
} from './status-language'

type Tone = 'ok' | 'warn' | 'block' | 'neutral'

function toneFor(check: ControlRoomReadinessCheck): Tone {
  // Route through the shared readiness vocabulary so this pill's tone cannot
  // diverge from the same status word elsewhere. toneForReadiness returns the
  // 3-tier 'ok'|'warn'|'err'; this panel renders 'err' as its 'block' tone
  // (both use --cc-err-soft). An earlier hand-rolled version defaulted an
  // unmatched status to a neutral grey that disagreed with the shared 'warn'
  // for a governed value like 'not_applicable'.
  const tier = toneForReadiness(check.status)
  return tier === 'err' ? 'block' : tier
}

function toneStyle(tone: Tone): { bg: string; fg: string; bd: string } {
  return {
    ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)', bd: 'var(--cc-ok)' },
    warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)', bd: 'var(--cc-warn)' },
    block: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-err)', bd: 'var(--cc-err)' },
    neutral: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)', bd: 'var(--cc-line)' },
  }[tone]
}

function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  const style = toneStyle(tone)
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: style.bg, color: style.fg }}
    >
      {label}
    </span>
  )
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md px-3 py-2" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  )
}

/**
 * The LPM-profile pill was the one StatusPill in this file whose tone did
 * not derive from the value it labels — a hardcoded `tone="warn"` that
 * happened to be right only because service.py currently ever emits one
 * value (`contract_only_not_station_device_evidence`). A future evidence
 * level (e.g. a real station-device-verified proof) would still render
 * warn. Every status containing "not_station_device" is the boundary
 * disclosure this pill exists to carry; anything else is informational.
 */
function lpmProfileTone(proofStatus: string): Tone {
  return proofStatus.includes('not_station_device') ? 'warn' : 'neutral'
}

function operatorRecoveryText(check: ControlRoomReadinessCheck): string {
  if (check.check_id === 'tsr-control-service') {
    return 'Open Control Room Setup to start or reconnect the local control service before On-Air use.'
  }
  return check.operator_action
}

function TechnicalDetail({ check }: { check: ControlRoomReadinessCheck }) {
  return (
    <details className="mt-2">
      <summary className="cursor-pointer font-semibold" style={{ color: 'var(--cc-ink-2)' }}>
        Technical detail
      </summary>
      <div className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>{check.operator_action}</div>
      <div className="mt-1 font-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
        Evidence: {check.evidence_ref}
      </div>
    </details>
  )
}

export function ControlRoomReadinessPanel({ report }: { report: ControlRoomReadinessReport }) {
  const blocking = report.checks.filter((check) => check.status === 'blocked')
  const warnings = report.checks.filter((check) => check.status === 'warning')
  const headlineTone: Tone = report.ready_for_on_air ? 'ok' : 'block'
  const headlineStyle = toneStyle(headlineTone)
  // F-RC3-7: operator screens speak operator words. The evidence-gating
  // vocabulary ("contract only", proof boundaries, Stage 0-1 lab profiles)
  // stays available under Technical detail, not in the always-visible copy.
  const stationDeviceStatus = report.station_device_ready
    ? 'Equipment verified'
    : 'Equipment check pending'
  // The banner used to hardcode its own copy of this sentence, and it drifted
  // from the backend's ("verified with" vs "verified against") — two subtly
  // different sentences making the same claim to one operator. The service
  // owns the wording, so render exactly the sentence it sends and keep NO
  // second copy in the panel: a hardcoded fallback would silently drift from
  // service.py again, which is the bug this fix exists to end. When the check
  // is absent (partial/older report) or its detail is empty, render no headline
  // at all — the explanatory line below already carries the meaning.
  const stationDeviceDetail = report.checks?.find(
    (check) => check.check_id === 'station-device-evidence',
  )?.detail
  // F1: this used to invent a FOURTH vocabulary ('Ready for local On-Air only'
  // / 'Ready for local On-Air' / 'Blocked') one screen away from System
  // Health's three sanctioned states. The nuance it carried is not lost: the
  // equipment pill beside it and the note above still say whether the room's
  // actual devices have been checked.
  const headlineReadiness =
    report.ready_for_on_air && !report.station_device_ready
      ? READINESS_CHECK_BEFORE_MEETING
      : report.ready_for_on_air
        ? READINESS_READY
        : READINESS_DO_NOT_BROADCAST_YET
  return (
    <section className="space-y-3">
      {!report.station_device_ready && (
        <div
          className="rounded-md p-3 text-xs"
          role="note"
          style={{
            background: 'var(--cc-warn-soft)',
            border: '1px solid var(--cc-warn)',
            color: 'var(--cc-ink)',
          }}
        >
          {stationDeviceDetail && (
            <strong className="block text-sm">{stationDeviceDetail}</strong>
          )}
          <span>
            You can register switchers and run dry runs now. On-air readiness is confirmed once
            a check against the room&apos;s actual devices passes.
          </span>
        </div>
      )}
      <div
        className="rounded-md p-3"
        style={{ background: headlineStyle.bg, border: `1px solid ${headlineStyle.bd}` }}
        aria-live="polite"
      >
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Control-room readiness</h2>
          <StatusPill label={headlineReadiness} tone={headlineTone} />
          <StatusPill
            label={stationDeviceStatus}
            tone={report.station_device_ready ? 'ok' : 'warn'}
          />
        </div>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>{report.summary}</p>
        <details className="mt-1">
          <summary
            className="cursor-pointer text-[11px] font-semibold"
            style={{ color: 'var(--cc-ink-2)' }}
          >
            Technical detail
          </summary>
          <p className="mt-1 text-[11px]" style={{ color: 'var(--cc-ink)' }}>{report.proof_boundary}</p>
        </details>
      </div>

      <div className="grid gap-2 sm:grid-cols-5">
        <Metric label="Devices" value={`${report.devices_enabled}/${report.devices_configured}`} />
        <Metric label="Surfaces" value={report.surfaces_configured} />
        <Metric label="Cues" value={report.cues_configured} />
        <Metric label="Open sessions" value={report.open_sessions} />
        <Metric label="On-Air" value={report.open_on_air_sessions} />
      </div>

      {(blocking.length > 0 || warnings.length > 0) && (
        <div className="space-y-2">
          {[...blocking, ...warnings].map((check) => (
            <div
              key={check.check_id}
              className="rounded-md p-3 text-xs"
              style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill label={readinessLabel(check.status)} tone={toneFor(check)} />
                <span className="font-semibold">{check.label}</span>
              </div>
              <div className="mt-1" style={{ color: 'var(--cc-ink-2)' }}>{check.detail}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span style={{ color: 'var(--cc-ink)' }}>{operatorRecoveryText(check)}</span>
                {check.status === 'blocked' && (
                  <Link
                    to="/control-room-setup"
                    className="rounded-md px-3 py-1.5 text-xs font-semibold"
                    style={{
                      background: 'var(--cc-brand)',
                      color: 'var(--cc-brand-ink)',
                    }}
                  >
                    Open Control Room Setup
                  </Link>
                )}
              </div>
              <TechnicalDetail check={check} />
            </div>
          ))}
        </div>
      )}

      <details className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
        <summary className="cursor-pointer font-semibold">LPM profile coverage</summary>
        <div className="mt-2 grid gap-2 lg:grid-cols-3">
          {report.lpm_profiles.map((profile) => {
            const requiredAbsences = profile.required_absences ?? []
            const egressDestinations = profile.egress_destinations ?? []
            const notClaimed = profile.not_claimed ?? []
            return (
              <div key={profile.profile_id} className="rounded-md p-2" style={{ background: 'var(--cc-surface-3)', border: '1px solid var(--cc-line)' }}>
                <div className="font-semibold">{profile.label}</div>
                <div className="mt-1">
                  <StatusPill label={stateLabel(profile.proof_status)} tone={lpmProfileTone(profile.proof_status)} />
                </div>
                <div className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                  {profile.devices.length} device contract(s), {profile.devices.reduce((sum, device) => sum + device.required_checks_count, 0)} required check(s)
                </div>
                {requiredAbsences.length > 0 && (
                  <div className="mt-2" style={{ color: 'var(--cc-ink-3)' }}>
                    Required absent: {requiredAbsences.join(', ')}
                  </div>
                )}
                {egressDestinations.length > 0 && (
                  <div className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                    Egress: {egressDestinations.join(', ')}
                  </div>
                )}
                {notClaimed.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-4" style={{ color: 'var(--cc-ink-3)' }}>
                    {notClaimed.map((claim) => <li key={claim}>{claim}</li>)}
                  </ul>
                )}
                <div className="mt-2 space-y-1">
                  {profile.devices.map((device) => (
                    <div key={device.device_contract_id} className="rounded px-2 py-1" style={{ background: 'var(--cc-surface-2)' }}>
                      <div className="font-semibold">{device.label}</div>
                      <div style={{ color: 'var(--cc-ink-3)' }}>
                        {device.integration_surface} - {device.proof_level}
                        {device.station_device_evidence_required
                          ? ' - station-device evidence required'
                          : ''}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </details>
    </section>
  )
}
