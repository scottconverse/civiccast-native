import type {
  LiveSessionCreate,
  LiveSessionResponse,
  LiveIngestPath,
  LiveIngestPlan,
  LiveRelayConfigResponse,
  LiveSourceProbeResponse,
  LiveSourceResponse,
  LiveSourceUpdate,
  PreflightCheckResult,
  PreflightEvaluation,
  PreflightInputs,
  RecordingTargetResponse,
} from './api.generated'

export type {
  LiveSessionCreate,
  LiveSessionResponse,
  LiveIngestPath,
  LiveIngestPlan,
  LiveRelayConfigResponse,
  LiveSourceProbeResponse,
  LiveSourceResponse,
  LiveSourceUpdate,
  PreflightCheckResult,
  PreflightEvaluation,
  PreflightInputs,
  RecordingTargetResponse,
}

export type LiveSessionState = LiveSessionResponse['state']
export type LiveIngestHealth = LiveIngestPath['health_state']
export type LiveIngestMode = LiveIngestPath['mode']
export type LiveRelayHealth = LiveRelayConfigResponse['health_state']
export type LiveRelayMode = LiveRelayConfigResponse['mode']
export type LiveSourceType = LiveSourceResponse['source_type']
export type PreflightStatus = PreflightCheckResult['status']

export const LIVE_STATE_META: Record<
  LiveSessionState,
  { label: string; tone: 'neutral' | 'info' | 'ok' | 'warn' | 'live' }
> = {
  idle: { label: 'Idle', tone: 'neutral' },
  preflight: { label: 'Pre-flight', tone: 'info' },
  on_air: { label: 'On air', tone: 'live' },
  ending: { label: 'Ending', tone: 'warn' },
  recorded: { label: 'Recorded', tone: 'ok' },
}

export const SOURCE_TYPE_LABEL: Record<LiveSourceType, string> = {
  rtmp: 'RTMP',
  rtsp: 'RTSP',
  ndi: 'NDI',
  srt: 'SRT',
}

export const RELAY_MODE_LABEL: Record<LiveRelayMode, string> = {
  local_rtmp: 'Local encoder',
  cloud_rtmp_relay: 'Cloud relay',
  direct_syndication: 'Direct platform',
}

export const RELAY_HEALTH_LABEL: Record<LiveRelayHealth, string> = {
  not_configured: 'Not configured',
  ready: 'Ready',
  degraded: 'Degraded',
  offline: 'Offline',
}

export const PREFLIGHT_LABELS: Record<string, string> = {
  network: 'Network reachable',
  storage: 'Recording storage',
  ai_runtime: 'AI runtime',
  live_source: 'Live source',
  recording_target: 'Recording target',
  operator_confirm: 'Operator confirmation',
  syndication: 'Syndication',
  internet_archive: 'Internet Archive',
  nas: 'NAS handoff',
}

// Field evidence (native beta candidate #17): the live room used to show
// the backend's internal reason code verbatim ("Resolve network.not_probed
// and re-run pre-flight") -- an operator has no way to act on a code like
// that. Every failed check's `message` from the backend is already a full
// plain-English sentence with the action embedded, so this map only needs
// to cover the short "Next step" callout beneath it, and it must never
// fall back to printing `reason_code` itself.
export const PREFLIGHT_NEXT_STEP: Record<string, string> = {
  'network.not_probed': 'Confirm this station has a network connection, then select Run pre-flight again.',
  'network.unreachable': "Check the station's network cable or Wi-Fi connection, then select Run pre-flight again.",
  'storage.not_probed': 'Confirm the recording drive is connected, then select Run pre-flight again.',
  'storage.insufficient_free_space': 'Free up space on the recording drive or attach more storage, then select Run pre-flight again.',
  'ai_runtime.not_ready': 'Check the AI runtime status in Setup, then select Run pre-flight again.',
  'live_session.not_found': 'Create the live session again before running pre-flight.',
  'live_source.none_configured_for_channel': 'Open Setup and add a source for this channel.',
  'live_source.selected_source_invalid': 'Choose a source that is configured for this channel above.',
  'live_source.not_probed': 'Select a source above so CivicCast can check it before going on air.',
  'live_source.unavailable': 'Confirm the encoder is powered on and sending video, then select Run pre-flight again.',
  'recording_target.none_configured': 'Open Setup and choose where CivicCast should save recordings.',
  'operator_confirm.not_confirmed': 'Check the confirmation box below, then select Run pre-flight again.',
}

export function preflightNextStep(reasonCode: string | null | undefined): string {
  if (!reasonCode) return 'Select Run pre-flight again after resolving the item above.'
  return PREFLIGHT_NEXT_STEP[reasonCode] ?? 'Resolve the item above, then select Run pre-flight again.'
}

// --- Observed live-source readiness (WP-07) --------------------------------
//
// A configured source used to count as ready because it existed. It is now an
// observation with an age, and the four states below are what the operator
// sees. Labels are deliberately plain: an operator glancing at a source card
// ninety seconds before a meeting gavels in should not have to decode a word.

export type LiveSourceReadiness = LiveSourceResponse['readiness']

export const SOURCE_READINESS_LABEL: Record<LiveSourceReadiness, string> = {
  ready: 'Delivering',
  stale: 'Needs re-check',
  failed: 'Not answering',
  never_probed: 'Not checked',
}

export const SOURCE_READINESS_TONE: Record<
  LiveSourceReadiness,
  'ok' | 'warn' | 'err' | 'neutral'
> = {
  ready: 'ok',
  stale: 'warn',
  failed: 'err',
  never_probed: 'neutral',
}

/**
 * "Checked 8 seconds ago" / "Checked 4 minutes ago" / "Never checked".
 *
 * Rounded to whole units on purpose: a decimal age reads as telemetry, and the
 * operator is deciding whether to trust it, not measuring it.
 */
export function observationAgeLabel(seconds: number | null | undefined): string {
  if (seconds == null) return 'Never checked'
  const whole = Math.max(0, Math.round(seconds))
  if (whole < 1) return 'Checked just now'
  if (whole < 60) return `Checked ${whole} second${whole === 1 ? '' : 's'} ago`
  const minutes = Math.round(whole / 60)
  if (minutes < 60) return `Checked ${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `Checked ${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  return `Checked ${days} day${days === 1 ? '' : 's'} ago`
}
