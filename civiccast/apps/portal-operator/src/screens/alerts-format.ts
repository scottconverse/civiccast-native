// Presentation helpers for the alerts UI. Kept out of AlertsScreen.tsx so that
// file only exports React components (react-refresh/only-export-components).
import type { AlertEvent } from '../types/api.generated'

export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'muted'

export function severityTone(severity: AlertEvent['severity']): Tone {
  if (severity === 'critical') return 'err'
  if (severity === 'warning') return 'warn'
  return 'info'
}

// Plain-English labels for the machine condition codes (no jargon for a
// public-access operator who has never heard of "schema drift").
const CONDITION_LABEL: Record<string, string> = {
  'off-air': 'Channel off air',
  'encoder-death': 'Encoder stopped',
  'server-crash': 'Server crashed',
  'schema-drift': 'Data format out of date',
  'relay-blocked': 'Relay blocked',
  'compliance-probe-fail': 'Cable compliance check failed',
  'missing-media': 'Missing media file',
  'commit-failure': 'Save to database failed',
  'takeover-stuck-2h': 'Live takeover stuck over 2 hours',
  'ai-runtime-down': 'AI engine is down',
  'disk-low': 'Disk space low',
  'clock-skew': 'Computer clock out of sync',
  'db-unreachable': 'Database unreachable',
  'service-down': 'CivicCast service is down',
  'self-test-fail': 'Automatic self-check failed',
}

export function formatCondition(condition: string): string {
  return CONDITION_LABEL[condition] ?? condition.replaceAll('-', ' ')
}
