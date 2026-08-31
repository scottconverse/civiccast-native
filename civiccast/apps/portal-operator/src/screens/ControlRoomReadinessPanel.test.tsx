import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import type { ControlRoomReadinessReport } from '../types/api.generated'
import { ControlRoomReadinessPanel } from './ControlRoomReadinessPanel'

afterEach(cleanup)

const REPORT: ControlRoomReadinessReport = {
  generated_at: '2026-06-30T12:00:00Z',
  ready_for_on_air: false,
  station_device_ready: false,
  // Mirrors the REAL string from civiccast/control_room/service.py so a
  // jargon regression in the always-visible summary trips this suite.
  summary: 'Control-room configuration has 1 blocker(s) before On-Air use.',
  devices_configured: 1,
  devices_enabled: 0,
  devices_missing_profile: ['dev_obs'],
  surfaces_configured: 1,
  cues_configured: 0,
  open_sessions: 0,
  open_on_air_sessions: 0,
  checks: [
    {
      check_id: 'device-profiles',
      label: 'Device profiles',
      status: 'blocked',
      severity: 'blocker',
      detail: 'Device(s) missing profiles: dev_obs.',
      operator_action: 'Save a device profile for every production device.',
      evidence_ref: 'device_profiles',
    },
    {
      check_id: 'station-device-evidence',
      label: 'Station-device evidence',
      status: 'warning',
      severity: 'warning',
      detail:
        "This control room has not been verified against your station's real equipment yet.",
      operator_action: 'Do not claim station-device readiness until station-device evidence exists.',
      evidence_ref: 'control_room.lpm_lab',
    },
  ],
  lpm_profiles: [
    {
      profile_id: 'fixed-studio-livestreaming',
      label: 'Fixed Studio + Livestreaming Studio',
      priority: 1,
      proof_status: 'contract_only_not_station_device_evidence',
      devices: [
        {
          profile_id: 'fixed-studio-livestreaming',
          device_contract_id: 'fixed-vmix-streaming-pc',
          label: 'vMix Streaming PC',
          device_class: 'vmix',
          integration_surface: 'vMix HTTP /api',
          proof_level: 'mocked',
          station_device_evidence_required: true,
          required_checks_count: 7,
        },
      ],
      required_absences: [],
      egress_destinations: [],
      not_claimed: ['No station-device readiness is claimed.'],
    },
  ],
  proof_boundary: 'Readiness is not clean Windows install evidence or station-device evidence.',
}

describe('ControlRoomReadinessPanel', () => {
  it('shows blockers in operator words and keeps the evidence detail available', () => {
    const { getAllByText, getByText, queryByText } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={REPORT} />
      </MemoryRouter>,
    )
    // F1 + banner-wall fix (field survey 2026-08-30): the page verdict phrase
    // appears exactly ONCE, in the headline banner. Blocking check rows no
    // longer repeat it in their own pill (a fresh box showed the same red
    // "DO NOT BROADCAST YET" five times); they carry severity via the red
    // border, and still never invent a fourth vocabulary or leak the raw enum.
    expect(getAllByText('Do not broadcast yet')).toHaveLength(1)
    expect(queryByText('Blocked')).toBeNull()
    expect(queryByText('blocked')).toBeNull()
    // F-RC3-7: the always-visible copy uses operator words; the evidence
    // vocabulary lives under Technical detail (still rendered below).
    expect(getByText('Equipment check pending')).toBeTruthy()
    expect(queryByText('Contract only')).toBeNull()
    expect(queryByText(/must not be described as station-device ready/)).toBeNull()
    expect(getByText('Device profiles')).toBeTruthy()
    expect(getByText(/missing profiles: dev_obs/)).toBeTruthy()
    expect(getByText(/Contract only not station device evidence/)).toBeTruthy()
    expect(getByText('Evidence: device_profiles')).toBeTruthy()
    expect(getByText('No station-device readiness is claimed.')).toBeTruthy()
    expect(getByText(/vMix HTTP \/api - mocked - station-device evidence required/)).toBeTruthy()
    // proof_boundary is still rendered (inside the Technical detail element).
    expect(getByText(/not clean Windows install evidence/)).toBeTruthy()
  })

  it('renders the backend station-device sentence in the banner, not its own copy', () => {
    // The panel used to hardcode this sentence and had drifted from the service
    // ("verified with" vs "verified against"), so an operator read two subtly
    // different sentences making the same claim. Nothing asserted either one's
    // text, so the F-RC4-3 wording fix could have been reverted with the whole
    // suite still green. Assert what the service sends actually reaches the eye.
    const { getByRole } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={REPORT} />
      </MemoryRouter>,
    )
    const backendDetail = REPORT.checks.find(
      (check) => check.check_id === 'station-device-evidence',
    )!.detail
    const banner = within(getByRole('note'))
    expect(banner.getByText(backendDetail)).toBeTruthy()
    // ...and the sentence it drifted into is gone for good.
    expect(banner.queryByText(/has not been verified with your station/)).toBeNull()
  })

  it('orders Technical detail toggles panel-first then per-check (e2e nth() contract)', () => {
    // The e2e spec opens toggles by index: first = the panel-level
    // proof-boundary details, nth(1) = the first check's evidence details
    // (blocking checks render before warnings). Pin that DOM order here so
    // an index drift fails fast in vitest instead of in CI's browser run.
    const { getAllByText } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={REPORT} />
      </MemoryRouter>,
    )
    const toggles = getAllByText('Technical detail')
    expect(toggles.length).toBe(3)
    const panelDetails = toggles[0].closest('details')
    expect(panelDetails?.textContent).toContain('not clean Windows install evidence')
    const firstCheckDetails = toggles[1].closest('details')
    expect(firstCheckDetails?.textContent).toContain('Evidence: device_profiles')
    const secondCheckDetails = toggles[2].closest('details')
    expect(secondCheckDetails?.textContent).toContain('Evidence: control_room.lpm_lab')
  })

  it('shows a local-ready state without turning it into station-device readiness', () => {
    const { getByText, queryByText } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={{
          ...REPORT,
          ready_for_on_air: true,
          summary:
            "Ready for local dry runs. On-air readiness is confirmed once a check against this room's actual devices passes.",
          devices_enabled: 1,
          checks: [{
            check_id: 'tsr-control-service',
            label: 'TSR control service',
            status: 'passed',
            severity: 'info',
            detail: 'A TSR control client is configured.',
            operator_action: 'Keep it supervised.',
            evidence_ref: 'control_room.tsr_client',
          }],
        }} />
      </MemoryRouter>,
    )
    // F1: 'Ready for local On-Air only' was a fourth vocabulary invented one
    // screen away from System Health's three sanctioned states. The nuance it
    // carried is still on screen -- in the equipment pill beside it.
    expect(getByText('Check before meeting')).toBeTruthy()
    expect(queryByText('Ready for local On-Air only')).toBeNull()
    expect(getByText('Equipment check pending')).toBeTruthy()
    expect(queryByText('Equipment verified')).toBeNull()
  })

  it('never renders a hardcoded second copy of the backend sentence, even when the check is absent', () => {
    // The banner headline must come from the backend's station-device-evidence
    // detail. When that check is absent from the report, the fallback must NOT
    // be a second hardcoded copy of the backend sentence (that copy can silently
    // drift from service.py, and no test would catch it — the exact two-copies
    // bug F-RC4-3 set out to end). It reuses the existing short status label.
    const { getByRole } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={{
          ...REPORT,
          station_device_ready: false,
          checks: [{
            check_id: 'tsr-control-service',
            label: 'TSR control service',
            status: 'passed',
            severity: 'info',
            detail: 'A TSR control client is configured.',
            operator_action: 'Keep it supervised.',
            evidence_ref: 'control_room.tsr_client',
          }],
        }} />
      </MemoryRouter>,
    )
    const banner = within(getByRole('note'))
    // No hardcoded copy of the backend sentence, in either wording — the panel
    // keeps no second copy to drift, so when the check is absent it renders no
    // headline at all.
    expect(banner.queryByText(/has not been verified (against|with) your station/)).toBeNull()
    // The banner still carries its meaning via the explanatory line below.
    expect(banner.getByText(/On-air readiness is confirmed once/)).toBeTruthy()
  })
})

describe('LPM profile coverage pill tone', () => {
  it('does not warn-color a profile whose evidence level is not the not-station-device-evidence boundary', () => {
    // Every other StatusPill in this file derives its tone from data; this
    // one was a hardcoded tone="warn" regardless of proof_status, so a future
    // evidence level (e.g. real station-device verification) would still
    // render yellow. 'station_device_verified' is a hypothetical value the
    // backend does not emit today, chosen to prove the tone is read from the
    // value and not merely coincidentally correct for today's one value.
    const { getByText } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={{
          ...REPORT,
          lpm_profiles: [{
            ...REPORT.lpm_profiles[0],
            proof_status: 'station_device_verified',
          }],
        }} />
      </MemoryRouter>,
    )
    const pill = getByText('Station device verified')
    expect(pill.style.background).not.toBe('var(--cc-warn-soft)')
  })

  it('still warn-colors the real contract-only boundary value the backend emits today', () => {
    const { getByText } = render(
      <MemoryRouter>
        <ControlRoomReadinessPanel report={REPORT} />
      </MemoryRouter>,
    )
    const pill = getByText('Contract only not station device evidence')
    expect(pill.style.background).toBe('var(--cc-warn-soft)')
  })
})
