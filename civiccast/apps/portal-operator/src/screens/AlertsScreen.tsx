import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  acknowledgeAlertEvent,
  createAlertChannel,
  deleteAlertChannel,
  getStaffIdentity,
  listAlertChannels,
  listAlertEvents,
  listAlertRules,
  updateAlertChannel,
  updateAlertRule,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type {
  AlertChannel,
  AlertChannelInput,
  AlertEvent,
  AlertRule,
} from '../types/api.generated'
import { formatCondition, severityTone, type Tone } from './alerts-format'
import { stateLabel, toneForDeliveryStatus } from './status-language'

const QUIET_HOURS_RE = /^([01]\d|2[0-3]):[0-5]\d$/

function quietHoursValid(value: string): boolean {
  return value.trim() === '' || QUIET_HOURS_RE.test(value.trim())
}

function AccessNote({ what }: { what: string }) {
  return (
    <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
      Managing {what} requires the setup admin or support admin role. Active alerts remain visible to you above.
    </div>
  )
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

const TONE: Record<Tone, { bg: string; fg: string }> = {
  ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  err: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
  info: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
  muted: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
}

function Pill({ label, tone }: { label: string; tone: Tone }) {
  const colors = TONE[tone]
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{ background: colors.bg, color: colors.fg }}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Active alerts
// ---------------------------------------------------------------------------

export function AlertEventRow({
  event,
  onAck,
  acking,
}: {
  event: AlertEvent
  onAck?: (eventId: string) => void
  acking?: boolean
}) {
  const acknowledged = event.acknowledged_at != null
  return (
    <article
      className="grid gap-2 rounded-md p-3 md:grid-cols-[1fr_auto]"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="m-0 text-sm font-semibold">{formatCondition(event.condition)}</h3>
          <Pill label={event.severity} tone={severityTone(event.severity)} />
          <Pill label={stateLabel(event.state)} tone={event.state === 'firing' ? 'err' : 'ok'} />
          {(event.occurrence_count ?? 1) > 1 && (
            <Pill label={`seen ${event.occurrence_count}×`} tone="muted" />
          )}
        </div>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {event.summary}
        </p>
        <p className="m-0 mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
          {event.resource_ref} · first seen {new Date(event.first_observed_at).toLocaleString()}
          {event.state === 'resolved' && event.resolved_at
            ? ` · resolved ${new Date(event.resolved_at).toLocaleString()}`
            : ` · last seen ${new Date(event.last_observed_at).toLocaleString()}`}
        </p>
        {acknowledged && (
          <p className="m-0 mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            Acknowledged by {event.acknowledged_by} on{' '}
            {new Date(event.acknowledged_at as string).toLocaleString()}
          </p>
        )}
      </div>
      <div className="flex items-start justify-end">
        {onAck && !acknowledged && (
          <button
            type="button"
            onClick={() => onAck(event.event_id)}
            disabled={acking}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
          >
            {acking ? 'Acknowledging...' : 'Acknowledge'}
          </button>
        )}
        {acknowledged && <Pill label="acknowledged" tone="ok" />}
      </div>
    </article>
  )
}

function ActiveAlertsSection() {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<'firing' | 'resolved'>('firing')
  const eventsQuery = useQuery({
    queryKey: ['alert-events', scope],
    queryFn: () => listAlertEvents({ state: scope, limit: 200 }),
    retry: false,
    refetchInterval: scope === 'firing' ? 10_000 : false,
  })
  const ack = useMutation({
    mutationFn: (eventId: string) => acknowledgeAlertEvent(eventId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alert-events'] })
      void queryClient.invalidateQueries({ queryKey: ['runtime-safe-to-air'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const events = eventsQuery.data ?? []
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Alerts</h2>
        <div className="flex gap-1 rounded-md p-0.5" style={{ background: 'var(--cc-surface-2)' }}>
          {(['firing', 'resolved'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setScope(value)}
              className="rounded-md px-3 py-1 text-xs font-semibold capitalize"
              style={{
                background: scope === value ? 'var(--cc-surface)' : 'transparent',
                color: scope === value ? 'var(--cc-ink)' : 'var(--cc-ink-3)',
              }}
            >
              {value === 'firing' ? 'Active' : 'Resolved'}
            </button>
          ))}
        </div>
      </div>
      {eventsQuery.isLoading && (
        <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Loading alerts...
        </div>
      )}
      {eventsQuery.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(eventsQuery.error, 'Alerts could not load.')}
        </div>
      )}
      {ack.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(ack.error, 'Could not acknowledge the alert.')}
        </div>
      )}
      {!eventsQuery.isLoading && events.length === 0 && (
        <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink-2)' }}>
          {scope === 'firing'
            ? 'No active alerts. Everything the watch box monitors is healthy.'
            : 'No resolved alerts in the recent history.'}
        </div>
      )}
      {/* Live region: the active list polls every 10s, so announce new alerts to AT. */}
      <div className="grid gap-2" aria-live="polite" aria-relevant="additions text">
        {events.map((event) => (
          <AlertEventRow
            key={event.event_id}
            event={event}
            onAck={scope === 'firing' ? (id) => ack.mutate(id) : undefined}
            acking={ack.isPending && ack.variables === event.event_id}
          />
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Alert rules
// ---------------------------------------------------------------------------

export function RuleRow({
  rule,
  onSave,
  saving,
}: {
  rule: AlertRule
  onSave: (ruleId: string, payload: { enabled: boolean; severity: AlertRule['severity']; re_alert_after_seconds: number; notify_on_resolve: boolean }) => void
  saving: boolean
}) {
  const [enabled, setEnabled] = useState(rule.enabled ?? true)
  const [severity, setSeverity] = useState<AlertRule['severity']>(rule.severity)
  const [reAlertMinutes, setReAlertMinutes] = useState(
    String(Math.round((rule.re_alert_after_seconds ?? 0) / 60)),
  )
  const [notifyOnResolve, setNotifyOnResolve] = useState(rule.notify_on_resolve ?? false)

  const minutes = Number.parseInt(reAlertMinutes, 10)
  const minutesValid = Number.isFinite(minutes) && minutes >= 0
  const dirty =
    enabled !== (rule.enabled ?? true) ||
    severity !== rule.severity ||
    notifyOnResolve !== (rule.notify_on_resolve ?? false) ||
    (minutesValid && minutes * 60 !== (rule.re_alert_after_seconds ?? 0))

  return (
    <article
      className="grid gap-2 rounded-md p-3"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-sm font-semibold">{formatCondition(rule.condition)}</h3>
        <span className="cc-mono text-[10px] uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          {rule.rule_id}
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span className="font-semibold">Enabled</span>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Severity</span>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as AlertRule['severity'])}
            className="rounded-md px-2 py-1"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Re-alert after (minutes)</span>
          <input
            value={reAlertMinutes}
            inputMode="numeric"
            onChange={(e) => setReAlertMinutes(e.target.value)}
            className="w-28 rounded-md px-2 py-1"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={notifyOnResolve} onChange={(e) => setNotifyOnResolve(e.target.checked)} />
          <span className="font-semibold">Notify on resolve</span>
        </label>
        <button
          type="button"
          disabled={!dirty || !minutesValid || saving}
          onClick={() =>
            onSave(rule.rule_id, {
              enabled,
              severity,
              re_alert_after_seconds: minutes * 60,
              notify_on_resolve: notifyOnResolve,
            })
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: dirty && minutesValid ? 'var(--cc-ink)' : 'var(--cc-surface-3)',
            color: dirty && minutesValid ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)',
          }}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </article>
  )
}

function AlertRulesSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient()
  const rulesQuery = useQuery({
    queryKey: ['alert-rules'],
    queryFn: listAlertRules,
    retry: false,
    enabled: canManage,  // don't fire the admin-only read for a non-admin (no red error)
  })
  const save = useMutation({
    mutationFn: ({ ruleId, payload }: { ruleId: string; payload: Parameters<typeof updateAlertRule>[1] }) =>
      updateAlertRule(ruleId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
  const rules = rulesQuery.data ?? []
  return (
    <section className="grid gap-3">
      <div>
        <h2 className="m-0 text-base font-semibold">Alert rules</h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Decide which problems raise an alert, how loud they are, and how often CivicCast re-notifies you while the problem persists.
        </p>
      </div>
      {!canManage ? (
        <AccessNote what="alert rules" />
      ) : (
        <>
          {rulesQuery.isLoading && (
            <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
              Loading rules...
            </div>
          )}
          {rulesQuery.error && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(rulesQuery.error, 'Alert rules could not load.')}
            </div>
          )}
          {save.error && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(save.error, 'Could not save the rule.')}
            </div>
          )}
          <div className="grid gap-2">
            {rules.map((rule) => (
              <RuleRow
                key={rule.rule_id}
                rule={rule}
                saving={save.isPending && save.variables?.ruleId === rule.rule_id}
                onSave={(ruleId, payload) => save.mutate({ ruleId, payload })}
              />
            ))}
          </div>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Alert channels (where alerts are delivered)
// ---------------------------------------------------------------------------

interface SecretRow {
  key: string
  value: string
}

const EMPTY_CHANNEL: AlertChannelInput = {
  kind: 'email',
  label: '',
  enabled: true,
  target_redacted: '',
  credential_handle: null,
  quiet_hours_start_utc: null,
  quiet_hours_end_utc: null,
  secret: null,
}

export function ChannelForm({
  initial,
  submitting,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: AlertChannelInput
  submitting: boolean
  submitLabel: string
  onSubmit: (payload: AlertChannelInput) => void
  onCancel?: () => void
}) {
  const [kind, setKind] = useState<AlertChannelInput['kind']>(initial.kind)
  const [label, setLabel] = useState(initial.label)
  const [target, setTarget] = useState(initial.target_redacted)
  const [enabled, setEnabled] = useState(initial.enabled ?? true)
  const [quietStart, setQuietStart] = useState(initial.quiet_hours_start_utc ?? '')
  const [quietEnd, setQuietEnd] = useState(initial.quiet_hours_end_utc ?? '')
  const [secretRows, setSecretRows] = useState<SecretRow[]>([])

  const quietOk = quietHoursValid(quietStart) && quietHoursValid(quietEnd)
  const valid = label.trim().length > 0 && target.trim().length > 0 && quietOk
  const hasStoredSecret = Boolean(initial.credential_handle)

  function buildPayload(): AlertChannelInput {
    const secretEntries = secretRows.filter((row) => row.key.trim() !== '')
    const secret =
      secretEntries.length > 0
        ? Object.fromEntries(secretEntries.map((row) => [row.key.trim(), row.value]))
        : null
    return {
      kind,
      label: label.trim(),
      enabled,
      target_redacted: target.trim(),
      credential_handle: initial.credential_handle ?? null,
      quiet_hours_start_utc: quietStart.trim() === '' ? null : quietStart.trim(),
      quiet_hours_end_utc: quietEnd.trim() === '' ? null : quietEnd.trim(),
      secret,
    }
  }

  return (
    <div className="grid gap-3 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Type</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as AlertChannelInput['kind'])}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="email">Email</option>
            <option value="sms">Text message (SMS)</option>
            <option value="webhook">Webhook</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Name</span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Example: Station manager email"
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs sm:col-span-2">
          <span className="font-semibold">Where to send (email, phone, or webhook URL)</span>
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="Example: ops@city.gov or https://hooks.example/alerts"
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Quiet hours start (UTC, HH:MM)</span>
          <input
            value={quietStart}
            onChange={(e) => setQuietStart(e.target.value)}
            placeholder="22:00"
            aria-invalid={!quietHoursValid(quietStart)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
          {!quietHoursValid(quietStart) && (
            <span style={{ color: 'var(--cc-err)' }}>Use 24-hour HH:MM, e.g. 22:00 (or leave blank).</span>
          )}
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Quiet hours end (UTC, HH:MM)</span>
          <input
            value={quietEnd}
            onChange={(e) => setQuietEnd(e.target.value)}
            placeholder="07:00"
            aria-invalid={!quietHoursValid(quietEnd)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
          {!quietHoursValid(quietEnd) && (
            <span style={{ color: 'var(--cc-err)' }}>Use 24-hour HH:MM, e.g. 07:00 (or leave blank).</span>
          )}
        </label>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span className="font-semibold">Enabled</span>
      </label>
      <div className="grid gap-2">
        <span className="text-xs font-semibold">Connection secret (optional — never shown again after saving)</span>
        {hasStoredSecret && (
          <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            A connection secret is already stored (its value is never shown). Add fields below only to replace it.
          </span>
        )}
        {secretRows.map((row, index) => (
          <div key={index} className="flex flex-wrap gap-2">
            <input
              value={row.key}
              onChange={(e) =>
                setSecretRows((rows) => rows.map((r, i) => (i === index ? { ...r, key: e.target.value } : r)))
              }
              placeholder="key (e.g. smtp_password)"
              className="flex-1 rounded-md px-2 py-1.5 text-xs"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
            <input
              value={row.value}
              type="password"
              onChange={(e) =>
                setSecretRows((rows) => rows.map((r, i) => (i === index ? { ...r, value: e.target.value } : r)))
              }
              placeholder="value"
              className="flex-1 rounded-md px-2 py-1.5 text-xs"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
            <button
              type="button"
              onClick={() => setSecretRows((rows) => rows.filter((_, i) => i !== index))}
              className="rounded-md px-2 py-1.5 text-xs"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setSecretRows((rows) => [...rows, { key: '', value: '' }])}
          className="w-fit rounded-md px-2 py-1 text-xs font-semibold"
          style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
        >
          Add secret field
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!valid || submitting}
          onClick={() => onSubmit(buildPayload())}
          className="rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: valid ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: valid ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
        >
          {submitting ? 'Saving...' : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

export function ChannelCard({
  channel,
  onUpdate,
  onDelete,
  updating,
  deleting,
}: {
  channel: AlertChannel
  onUpdate: (channelId: string, payload: AlertChannelInput) => void
  onDelete: (channelId: string) => void
  updating: boolean
  deleting: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const tone: Tone = channel.last_delivery_status
    ? toneForDeliveryStatus(channel.last_delivery_status)
    : 'muted'
  return (
    <article
      className="grid gap-2 rounded-md p-3"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="m-0 text-sm font-semibold">{channel.label}</h3>
            <Pill label={channel.kind} tone="info" />
            {channel.enabled === false && <Pill label="disabled" tone="muted" />}
            {channel.last_delivery_status && (
              <Pill label={stateLabel(channel.last_delivery_status)} tone={tone} />
            )}
          </div>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {channel.target_redacted}
            {channel.quiet_hours_start_utc && channel.quiet_hours_end_utc
              ? ` · quiet ${channel.quiet_hours_start_utc}–${channel.quiet_hours_end_utc} UTC`
              : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
          >
            {editing ? 'Close' : 'Edit'}
          </button>
          <button
            type="button"
            onClick={() => {
              // Two-step confirm: a misclick must not silently remove the only
              // path that pages a sleeping operator.
              if (confirmDelete) {
                onDelete(channel.channel_id)
                setConfirmDelete(false)
              } else {
                setConfirmDelete(true)
              }
            }}
            disabled={deleting}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{
              background: confirmDelete ? 'var(--cc-err)' : 'var(--cc-err-soft)',
              color: confirmDelete ? 'var(--cc-ink-inv)' : 'var(--cc-err)',
            }}
          >
            {deleting ? 'Removing...' : confirmDelete ? 'Confirm delete?' : 'Delete'}
          </button>
        </div>
      </div>
      {editing && (
        <ChannelForm
          initial={{
            kind: channel.kind,
            label: channel.label,
            enabled: channel.enabled ?? true,
            target_redacted: channel.target_redacted,
            credential_handle: channel.credential_handle ?? null,
            quiet_hours_start_utc: channel.quiet_hours_start_utc ?? null,
            quiet_hours_end_utc: channel.quiet_hours_end_utc ?? null,
            secret: null,
          }}
          submitting={updating}
          submitLabel="Save changes"
          onSubmit={(payload) => {
            onUpdate(channel.channel_id, payload)
            setEditing(false)
          }}
          onCancel={() => setEditing(false)}
        />
      )}
    </article>
  )
}

function AlertChannelsSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const channelsQuery = useQuery({
    queryKey: ['alert-channels'],
    queryFn: listAlertChannels,
    retry: false,
    enabled: canManage,  // admin-only read; skip for a non-admin so no red error box
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['alert-channels'] })
  const create = useMutation({
    mutationFn: (payload: AlertChannelInput) => createAlertChannel(payload),
    onSuccess: () => {
      void invalidate()
      setCreating(false)
    },
  })
  const update = useMutation({
    mutationFn: ({ channelId, payload }: { channelId: string; payload: AlertChannelInput }) =>
      updateAlertChannel(channelId, payload),
    onSuccess: () => void invalidate(),
  })
  const remove = useMutation({
    mutationFn: (channelId: string) => deleteAlertChannel(channelId),
    onSuccess: () => void invalidate(),
  })
  const channels = channelsQuery.data ?? []
  const error = create.error ?? update.error ?? remove.error
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Where alerts go</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Email, text-message, or webhook destinations that receive alerts. Connection
            secrets are stored on the station and never shown back; the destination address
            is shown in full.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setCreating((value) => !value)}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
          >
            {creating ? 'Close' : 'Add destination'}
          </button>
        )}
      </div>
      {!canManage ? (
        <AccessNote what="alert destinations" />
      ) : (
        <>
          {error != null && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(error, 'The destination change could not be saved.')}
            </div>
          )}
          {creating && (
            <ChannelForm
              initial={EMPTY_CHANNEL}
              submitting={create.isPending}
              submitLabel="Create destination"
              onSubmit={(payload) => create.mutate(payload)}
              onCancel={() => setCreating(false)}
            />
          )}
          {channelsQuery.isLoading && (
            <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
              Loading destinations...
            </div>
          )}
          {channelsQuery.error && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(channelsQuery.error, 'Destinations could not load.')}
            </div>
          )}
          {!channelsQuery.isLoading && channels.length === 0 && (
            <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
              No alert destinations yet. Add one so the station can reach you when something needs attention.
            </div>
          )}
          <div className="grid gap-2">
            {channels.map((channel) => (
              <ChannelCard
                key={channel.channel_id}
                channel={channel}
                updating={update.isPending && update.variables?.channelId === channel.channel_id}
                deleting={remove.isPending && remove.variables === channel.channel_id}
                onUpdate={(channelId, payload) => update.mutate({ channelId, payload })}
                onDelete={(channelId) => remove.mutate(channelId)}
              />
            ))}
          </div>
        </>
      )}
    </section>
  )
}

export function AlertsScreen() {
  const identityQuery = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity, retry: false })
  // Fail CLOSED (matches CableVerificationCard): rules/channels management is gated on
  // a successful identity carrying an admin role. Active alerts stay visible to all
  // operator roles. The server enforces the gate independently; this keeps the UI honest
  // (a calm "needs admin" note instead of red "could not load" errors for a meeting_operator).
  const canManage =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'setup_admin') ||
      hasOperatorRole(identityQuery.data, 'support_admin'))
  return (
    <div className="grid gap-6 px-6 py-5">
      <header>
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Operations
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Alerts &amp; monitoring</h1>
        <p className="m-0 mt-1 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          See what the watch box has flagged, tune which problems raise an alert, and choose where alerts are sent.
        </p>
      </header>
      <ActiveAlertsSection />
      <AlertRulesSection canManage={canManage} />
      <AlertChannelsSection canManage={canManage} />
    </div>
  )
}
