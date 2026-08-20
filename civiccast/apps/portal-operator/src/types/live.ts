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
