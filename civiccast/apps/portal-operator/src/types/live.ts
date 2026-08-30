import type {
  LiveSessionCreate,
  LiveSessionResponse,
  LiveIngestPath,
  LiveIngestPlan,
  LiveRelayConfigResponse,
  LiveSourceResponse,
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
  LiveSourceResponse,
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
