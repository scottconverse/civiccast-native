// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * GauntletGate F1: the operator console must never put a machine enum on
 * screen where the operator language guide has a phrase for it.
 */

import { describe, expect, it } from 'vitest'

import {
  READINESS_CHECK_BEFORE_MEETING,
  READINESS_DO_NOT_BROADCAST_YET,
  READINESS_NEEDS_IT_HELP,
  READINESS_NOT_SET_UP_YET,
  READINESS_PHRASES,
  READINESS_READY,
  isKnownReadinessStatus,
  readinessLabel,
  stateLabel,
  toneForDeliveryStatus,
  toneForEgressState,
  toneForReadiness,
} from './status-language'

describe('readinessLabel', () => {
  it('returns a guide phrase for every status it recognises', () => {
    const samples = ['ready', 'needs_it_help', 'not_set_up', 'blocked', 'warning', '']
    for (const sample of samples) {
      expect(READINESS_PHRASES).toContain(readinessLabel(sample))
    }
  })

  it('never lets an underscore reach the screen', () => {
    for (const sample of ['needs_it_help', 'not_set_up', 'credential_or_secret_required']) {
      expect(readinessLabel(sample)).not.toMatch(/_/)
    }
  })

  it('renders "Needs IT help" with the acronym intact', () => {
    // The bug this replaces rendered "needs it help" — lowercase, and the
    // "IT" reads as a stray pronoun.
    expect(readinessLabel('needs_it_help')).toBe(READINESS_NEEDS_IT_HELP)
    expect(readinessLabel('needs_it_help')).toBe('Needs IT help')
  })

  it('maps each guide category to its sanctioned phrase', () => {
    expect(readinessLabel('ready')).toBe(READINESS_READY)
    expect(readinessLabel('ok')).toBe(READINESS_READY)
    expect(readinessLabel('needs_attention')).toBe(READINESS_CHECK_BEFORE_MEETING)
    expect(readinessLabel('needs_live_proof')).toBe(READINESS_CHECK_BEFORE_MEETING)
    expect(readinessLabel('not_set_up')).toBe(READINESS_NOT_SET_UP_YET)
    expect(readinessLabel('credential_or_secret_required')).toBe(READINESS_NOT_SET_UP_YET)
    expect(readinessLabel('hardware_required')).toBe(READINESS_NEEDS_IT_HELP)
  })

  it('treats a blocking check as "Do not broadcast yet", not "Not set up yet"', () => {
    // The guide lists `blocked` under the Avoid column for "Not set up yet",
    // but the Control Room emits it for a check that stops tonight's
    // broadcast — the guide's own definition of "Do not broadcast yet".
    expect(readinessLabel('blocked')).toBe(READINESS_DO_NOT_BROADCAST_YET)
    expect(readinessLabel('failed')).toBe(READINESS_DO_NOT_BROADCAST_YET)
  })

  it('never invents a readiness verdict for an unknown status', () => {
    // Caught by running the real console: defaulting unknowns to "Check
    // before meeting" made ten restore-checklist rows (state `pending`,
    // meaning "the rehearsal has not run") each claim something needed
    // attention before a meeting. Nothing did. An unknown status is reported
    // as what the backend said, sentence-cased — never as a readiness phrase.
    expect(readinessLabel('some_future_backend_state')).toBe('Some future backend state')
    expect(readinessLabel('some_future_backend_state')).not.toMatch(/_/)
    expect(READINESS_PHRASES).not.toContain(readinessLabel('some_future_backend_state'))
    expect(readinessLabel('pending')).toBe('Not run yet')
  })

  it('treats a missing status as not set up', () => {
    expect(readinessLabel(null)).toBe(READINESS_NOT_SET_UP_YET)
    expect(readinessLabel(undefined)).toBe(READINESS_NOT_SET_UP_YET)
  })

  it('is case- and whitespace-insensitive', () => {
    expect(readinessLabel(' READY ')).toBe(READINESS_READY)
  })

  it('reports which statuses it recognises', () => {
    expect(isKnownReadinessStatus('needs_it_help')).toBe(true)
    expect(isKnownReadinessStatus('not_a_real_status')).toBe(false)
  })

  it('covers every readiness enum the API contract can emit', () => {
    // Sourced from types/api.generated.ts: SystemHealthCheck.state,
    // ProviderReadinessItem.status/proof_status, BackupStatus.status, and
    // ControlRoomReadinessCheck.status. If the backend adds a value, this
    // fails and the table gets a deliberate decision instead of a silent
    // fallback.
    const contractStatuses = [
      'ready',
      'needs_attention',
      'needs_it_help',
      'not_set_up',
      'needs_live_proof',
      'not_configured',
      'proof_passed',
      'proof_failed_redaction',
      'skipped_optional',
      'blocked',
      'warning',
      'ok',
    ]
    const unmapped = contractStatuses.filter((status) => !isKnownReadinessStatus(status))
    expect(unmapped).toEqual([])
  })
})

describe('toneForReadiness', () => {
  it('agrees with readinessLabel: never a stricter or looser tier than the phrase implies', () => {
    expect(toneForReadiness('ready')).toBe('ok')
    expect(toneForReadiness('ok')).toBe('ok')
    expect(toneForReadiness('needs_attention')).toBe('warn')
    expect(toneForReadiness('needs_live_proof')).toBe('warn')
    expect(toneForReadiness('blocked')).toBe('err')
    expect(toneForReadiness('failed')).toBe('err')
    expect(toneForReadiness('not_set_up')).toBe('warn')
    expect(toneForReadiness('needs_it_help')).toBe('err')
  })

  it('never puts "Check before meeting" text in an err-tone pill', () => {
    // The exact bug: needs_attention read "Check before meeting" text in a
    // "Do not broadcast yet" red pill on four color-severity call sites.
    // Assert the fixed relationship holds for every enum key the readiness
    // table recognises: same phrase from readinessLabel -> same tier here.
    for (const enumKey of [
      'ready', 'ok', 'pass', 'proof_passed',
      'needs_attention', 'needs_live_proof', 'warning', 'degraded',
      'blocked', 'fail', 'failed', 'proof_failed_redaction', 'error',
      'not_set_up', 'not_configured', 'not_tested',
      'needs_it_help', 'hardware_required',
    ]) {
      const label = readinessLabel(enumKey)
      const tone = toneForReadiness(enumKey)
      if (label === READINESS_READY) expect(tone).toBe('ok')
      if (label === READINESS_CHECK_BEFORE_MEETING) expect(tone).toBe('warn')
      if (label === READINESS_DO_NOT_BROADCAST_YET) expect(tone).toBe('err')
      if (label === READINESS_NOT_SET_UP_YET) expect(tone).toBe('warn')
      if (label === READINESS_NEEDS_IT_HELP) expect(tone).toBe('err')
    }
  })

  it('treats an unrecognised status as attention-worthy, not a false pass or false failure', () => {
    expect(toneForReadiness('some_future_backend_state')).toBe('warn')
    expect(toneForReadiness(null)).toBe('warn')
  })
})

describe('toneForEgressState', () => {
  it('is one shared rule so the two screens rendering this feed cannot disagree', () => {
    expect(toneForEgressState('ON_AIR')).toBe('ok')
    expect(toneForEgressState('ERROR')).toBe('err')
    for (const state of ['STOPPED', 'STARTING', 'STOPPING', 'DRAINING', 'TRANSITIONING', 'FALLBACK_SLATE']) {
      expect(toneForEgressState(state)).toBe('warn')
    }
  })

  it('defaults an unknown or missing state to attention-worthy, never a false "on air"', () => {
    expect(toneForEgressState('some_future_state')).toBe('warn')
    expect(toneForEgressState(null)).toBe('warn')
    expect(toneForEgressState(undefined)).toBe('warn')
  })
})

describe('stateLabel', () => {
  it('never leaves an underscore on screen', () => {
    for (const sample of ['archive_pending', 'pending_ingest', 'dead_letter', 'on_air']) {
      expect(stateLabel(sample)).not.toMatch(/_/)
    }
  })

  it('sentence-cases a plain lifecycle value', () => {
    expect(stateLabel('archive_pending')).toBe('Archive pending')
    expect(stateLabel('publishing')).toBe('Publishing')
  })

  it('uses operator words for values that read badly as-is', () => {
    expect(stateLabel('on_air')).toBe('On air')
    expect(stateLabel('dead_letter')).toBe('Undeliverable')
    expect(stateLabel('reach_degraded')).toBe('Reaching fewer places than planned')
  })

  it('translates every outgoing-channel-feed state the same way for every screen that shows it', () => {
    // GauntletGate F1's exact bug ("two translations, one enum") recurred
    // here: SystemHealthScreen.tsx and ChannelOpsScreen.tsx each kept a
    // byte-for-byte copy of this switch instead of routing through here.
    expect(stateLabel('FALLBACK_SLATE')).toBe('Showing slate')
    expect(stateLabel('STARTING')).toBe('Starting')
    expect(stateLabel('STOPPING')).toBe('Stopping')
    expect(stateLabel('DRAINING')).toBe('Finishing current item')
    expect(stateLabel('TRANSITIONING')).toBe('Changing source')
    expect(stateLabel('ERROR')).toBe('Needs attention')
    expect(stateLabel('STOPPED')).toBe('Stopped')
  })

  it('agrees with the readiness table where the two overlap', () => {
    expect(stateLabel('not_configured')).toBe(readinessLabel('not_configured'))
    expect(stateLabel('needs_it_help')).toBe(readinessLabel('needs_it_help'))
  })

  it('falls back rather than rendering an empty pill', () => {
    expect(stateLabel(null)).toBe('Unknown')
    expect(stateLabel('', 'Not run')).toBe('Not run')
  })
})

describe('toneForDeliveryStatus', () => {
  it('is green for a delivered notification, by any of the backend success words', () => {
    // The backend records success as delivered / sent / success -- all must read ok.
    expect(toneForDeliveryStatus('delivered')).toBe('ok')
    expect(toneForDeliveryStatus('sent')).toBe('ok')
    expect(toneForDeliveryStatus('success')).toBe('ok')
  })

  it('treats queued the same in-flight amber as pending', () => {
    expect(toneForDeliveryStatus('queued')).toBe('warn')
  })

  it('is red for a failed or dead-lettered notification', () => {
    expect(toneForDeliveryStatus('failed')).toBe('err')
    expect(toneForDeliveryStatus('dead_letter')).toBe('err')
    expect(toneForDeliveryStatus('error')).toBe('err')
  })

  it('is amber -- not neutral -- for anything still in flight or unknown', () => {
    // A queued/retrying channel must not read the same as "nothing to see".
    expect(toneForDeliveryStatus('pending')).toBe('warn')
    expect(toneForDeliveryStatus('retrying')).toBe('warn')
    expect(toneForDeliveryStatus(null)).toBe('warn')
    expect(toneForDeliveryStatus('')).toBe('warn')
  })
})
