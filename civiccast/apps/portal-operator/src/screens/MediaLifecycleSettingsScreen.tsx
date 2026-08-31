// S7 media lifecycle spec §5/§10: watch-folder configuration, retention
// automation rules, and the storage budget view -- three related operator
// settings surfaces grouped on one screen (each has its own loading/empty/
// error state; a failure in one section never blocks the other two).

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  applyRetentionPolicies,
  createRetentionPolicy,
  createWatchFolderConfig,
  deleteRetentionPolicy,
  deleteWatchFolderConfig,
  getStorageBudget,
  listRetentionPolicies,
  listWatchFolderConfigs,
  scanWatchFolderNow,
} from '../api/client'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FolderBrowser } from '../components/media-lifecycle/FolderBrowser'
import { useToast } from '../components/toast-context'
import type {
  AssetRetentionPolicyResponse,
  StorageBudgetResponse,
  WatchFolderConfigResponse,
} from '../types/api.generated'

const RETENTION_POLICIES = ['default', 'permanent', 'meeting', 'short'] as const

function fmtRelativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'never'
  const diffSeconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (diffSeconds < 60) return `${diffSeconds}s ago`
  const diffMinutes = Math.round(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  const diffDays = Math.round(diffHours / 24)
  return `${diffDays}d ago`
}

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function SectionCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section
      className="mx-6 my-4 flex flex-col gap-3 rounded-md p-5"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <h2 className="m-0 text-base font-semibold">{title}</h2>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {subtitle}
        </p>
      </div>
      {children}
    </section>
  )
}

function InlineError({ error }: { error: Error }) {
  const isApiError = error instanceof ApiError
  // --cc-err text on --cc-err-soft carries the same WCAG AA contrast risk
  // measured (and confirmed via axe-core) for the ok/warn siblings of this
  // pattern elsewhere in this PR -- --cc-ink stays safe regardless of theme.
  return (
    <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}>
      {isApiError && error.detail ? error.detail : `Request failed: ${error.message}`}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Watch folders
// ---------------------------------------------------------------------------

// S7 watch-folder poll daemon status. Health/poll/ingest fields are worker-
// owned (never operator-set) -- see WatchFolderConfigResponse. Surfacing
// "degraded" here is the point: an unreachable monitor_path (USB unplugged,
// NAS/SMB share down) must be a visible state on the config, never a
// silent failure the operator only discovers when a meeting recording
// never shows up.
//
// Candidate #17 tester finding 4: "Last poll: never" with zero other
// feedback read as broken even though the daemon HAD auto-ingested within
// about a minute. A fresh, never-polled config now says so in words (with
// the actual poll cadence) instead of a bare "never," and a "Scan now"
// button gives the operator a way to force an immediate check + a real
// result instead of waiting out the interval.
function WatchFolderStatus({
  config,
  onScanNow,
  scanning,
  scanError,
}: {
  config: WatchFolderConfigResponse
  onScanNow: () => void
  scanning: boolean
  scanError: string | null
}) {
  const isDegraded = config.health_status === 'degraded'
  const isUnknown = config.health_status === 'unknown'
  const statusColor = isDegraded ? 'var(--cc-err)' : isUnknown ? 'var(--cc-ink-3)' : 'var(--cc-ink-2)'
  const statusLabel = isDegraded ? 'Degraded' : isUnknown ? 'Not scanned yet' : 'OK'

  return (
    <div className="flex flex-col items-end gap-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
      <span className="font-medium" style={{ color: statusColor }} role={isDegraded ? 'alert' : undefined}>
        {statusLabel}
      </span>
      {isUnknown ? (
        <span className="max-w-[220px] text-right">
          No automatic check has run yet — the next one runs within{' '}
          {config.poll_interval_seconds}s, or use Scan now.
        </span>
      ) : (
        <>
          <span>Last poll: {fmtRelativeTime(config.last_poll_at)}</span>
          <span>Last ingest: {fmtRelativeTime(config.last_ingest_at)}</span>
        </>
      )}
      {isDegraded && config.degraded_reason && (
        <span
          className="max-w-[220px] text-right"
          style={{ color: 'var(--cc-err)' }}
          title={config.degraded_reason}
        >
          {config.degraded_reason}
        </span>
      )}
      <button
        type="button"
        onClick={onScanNow}
        disabled={scanning || !config.enabled}
        className="mt-1 rounded-md px-2 py-1 text-[11px] font-medium"
        style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
      >
        {scanning ? 'Scanning…' : 'Scan now'}
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {scanning ? `Scanning ${config.monitor_path} now.` : ''}
      </span>
      {scanError && (
        <span role="alert" className="max-w-[220px] text-right" style={{ color: 'var(--cc-err)' }}>
          {scanError}
        </span>
      )}
    </div>
  )
}

function WatchFolderSection() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [monitorPath, setMonitorPath] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const [scanningId, setScanningId] = useState<string | null>(null)
  // "Remove" is a one-click destructive action on a live ingest path — it
  // stages a confirmation dialog naming the folder before anything is deleted.
  const [confirmingRemove, setConfirmingRemove] = useState<WatchFolderConfigResponse | null>(null)
  const [scanError, setScanError] = useState<{ configId: string; message: string } | null>(null)
  const query = useQuery<WatchFolderConfigResponse[], Error>({
    queryKey: ['watch-folder-configs'],
    queryFn: listWatchFolderConfigs,
    retry: false,
  })
  const createMutation = useMutation({
    mutationFn: () => createWatchFolderConfig({ monitor_path: monitorPath, settle_window_seconds: 10, enabled: true }),
    onSuccess: () => {
      setMonitorPath('')
      queryClient.invalidateQueries({ queryKey: ['watch-folder-configs'] })
      toast.push({ tone: 'success', message: 'Watch folder added.' })
    },
    onError: (error: Error) =>
      toast.push({
        tone: 'error',
        message: 'Could not add watch folder.',
        detail: error instanceof ApiError ? error.detail : error.message,
      }),
  })
  const deleteMutation = useMutation({
    mutationFn: (configId: string) => deleteWatchFolderConfig(configId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['watch-folder-configs'] }),
  })

  async function handleScanNow(configId: string) {
    setScanningId(configId)
    setScanError(null)
    try {
      const result = await scanWatchFolderNow(configId)
      queryClient.setQueryData<WatchFolderConfigResponse[]>(['watch-folder-configs'], (current) =>
        (current ?? []).map((c) => (c.config_id === configId ? result.config : c)),
      )
      if (result.files_ingested > 0 || result.files_reprocessed > 0) {
        toast.push({
          tone: 'success',
          message: `Scanned ${result.config.monitor_path}: ${result.files_ingested + result.files_reprocessed} file(s) ingested.`,
        })
        queryClient.invalidateQueries({ queryKey: ['staff-assets'] })
        queryClient.invalidateQueries({ queryKey: ['readiness-dashboard'] })
      } else if (!result.healthy) {
        toast.push({
          tone: 'error',
          message: `Could not scan ${result.config.monitor_path}.`,
          detail: result.error ?? undefined,
        })
      } else {
        toast.push({
          tone: 'info',
          message:
            result.files_seen === 0
              ? `Scanned ${result.config.monitor_path}: no files found.`
              : `Scanned ${result.config.monitor_path}: ${result.files_seen} file(s) seen, nothing new to ingest.`,
        })
      }
    } catch (error) {
      setScanError({
        configId,
        message: error instanceof ApiError ? (error.detail ?? error.message) : 'Scan failed.',
      })
    } finally {
      setScanningId(null)
    }
  }

  return (
    <SectionCard
      title="Watch folders"
      subtitle="Auto-ingest files dropped into a local disk, USB, or NAS/SMB directory. Hands-off after setup."
    >
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (monitorPath.trim()) createMutation.mutate()
        }}
      >
        <input
          aria-label="Watch folder path"
          placeholder="/mnt/nas/incoming or D:\\incoming"
          value={monitorPath}
          onChange={(e) => setMonitorPath(e.target.value)}
          className="flex-1 rounded-md px-3 py-1.5 text-sm"
          style={{ minWidth: 240, border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
        />
        <button
          type="button"
          onClick={() => setBrowsing(true)}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
        >
          Browse…
        </button>
        <button
          type="submit"
          disabled={!monitorPath.trim() || createMutation.isPending}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {createMutation.isPending ? 'Adding…' : 'Add watch folder'}
        </button>
      </form>

      {browsing && (
        <FolderBrowser
          initialPath={monitorPath}
          onClose={() => setBrowsing(false)}
          onSelect={(path) => {
            setMonitorPath(path)
            setBrowsing(false)
          }}
        />
      )}

      {query.isLoading && <div className="h-10 w-full animate-pulse rounded-md" style={{ background: 'var(--cc-surface-2)' }} />}
      {query.isError && <InlineError error={query.error} />}
      {query.isSuccess && query.data.length === 0 && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No watch folders configured yet. Every asset comes in via manual upload until you add one.
        </p>
      )}
      {query.isSuccess && query.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {query.data.map((config) => (
            <li
              key={config.config_id}
              className="flex items-center justify-between gap-3 rounded-md px-3 py-2 text-xs"
              style={{ background: 'var(--cc-surface-2)' }}
            >
              <span className="cc-mono">{config.monitor_path}</span>
              <div className="flex items-center gap-3">
                <span style={{ color: config.enabled ? 'var(--cc-ink)' : 'var(--cc-ink-3)' }}>
                  {config.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <WatchFolderStatus
                  config={config}
                  onScanNow={() => handleScanNow(config.config_id)}
                  scanning={scanningId === config.config_id}
                  scanError={scanError?.configId === config.config_id ? scanError.message : null}
                />
                <button
                  type="button"
                  onClick={() => setConfirmingRemove(config)}
                  className="rounded-md px-2 py-1"
                  style={{ border: '1px solid var(--cc-err)', color: 'var(--cc-ink)' }}
                  aria-label={`Remove watch folder ${config.monitor_path}`}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {confirmingRemove && (
        <ConfirmDialog
          title={`Remove the watch folder ${confirmingRemove.monitor_path}?`}
          body="New files dropped there stop being ingested automatically. Assets already ingested from this folder are not affected."
          confirmLabel="Remove folder"
          busy={deleteMutation.isPending}
          onConfirm={() =>
            deleteMutation.mutate(confirmingRemove.config_id, {
              onSettled: () => setConfirmingRemove(null),
            })
          }
          onCancel={() => setConfirmingRemove(null)}
        />
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Retention automation
// ---------------------------------------------------------------------------

function RetentionPolicySection() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState('')
  const [matchMeetingBody, setMatchMeetingBody] = useState('')
  const [policy, setPolicy] = useState<(typeof RETENTION_POLICIES)[number]>('meeting')
  // Same one-click-destructive rule as watch folders: confirm before removing.
  const [confirmingRemove, setConfirmingRemove] = useState<AssetRetentionPolicyResponse | null>(null)

  const query = useQuery<AssetRetentionPolicyResponse[], Error>({
    queryKey: ['retention-policies'],
    queryFn: listRetentionPolicies,
    retry: false,
  })
  const createMutation = useMutation({
    mutationFn: () =>
      createRetentionPolicy({
        name,
        match_meeting_body: matchMeetingBody || null,
        retention_policy: policy,
        priority: 0,
        enabled: true,
      }),
    onSuccess: () => {
      setName('')
      setMatchMeetingBody('')
      queryClient.invalidateQueries({ queryKey: ['retention-policies'] })
      toast.push({ tone: 'success', message: 'Retention rule added.' })
    },
    onError: (error: Error) =>
      toast.push({
        tone: 'error',
        message: 'Could not add retention rule.',
        detail: error instanceof ApiError ? error.detail : error.message,
      }),
  })
  const deleteMutation = useMutation({
    mutationFn: (policyId: string) => deleteRetentionPolicy(policyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['retention-policies'] }),
  })
  const applyMutation = useMutation({
    mutationFn: applyRetentionPolicies,
    onSuccess: (result) =>
      toast.push({ tone: 'success', message: `Applied rules: ${result.assets_changed} asset(s) updated.` }),
    onError: (error: Error) =>
      toast.push({
        tone: 'error',
        message: 'Could not apply retention rules.',
        detail: error instanceof ApiError ? error.detail : error.message,
      }),
  })

  return (
    <SectionCard
      title="Retention automation"
      subtitle="Assign a retention policy automatically by meeting series, e.g. 'City Council' → meeting retention. Never auto-deletes -- expired assets are flagged for records-clerk review."
    >
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) createMutation.mutate()
        }}
      >
        <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
          Rule name
          <input
            aria-label="Rule name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-md px-3 py-1.5 text-sm"
            style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
          Meeting body (exact match)
          <input
            aria-label="Match meeting body"
            placeholder="City Council"
            value={matchMeetingBody}
            onChange={(e) => setMatchMeetingBody(e.target.value)}
            className="rounded-md px-3 py-1.5 text-sm"
            style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]" style={{ color: 'var(--cc-ink-2)' }}>
          Retention policy
          <select
            aria-label="Retention policy"
            value={policy}
            onChange={(e) => setPolicy(e.target.value as (typeof RETENTION_POLICIES)[number])}
            className="rounded-md px-3 py-1.5 text-sm"
            style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
          >
            {RETENTION_POLICIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={!name.trim() || createMutation.isPending}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {createMutation.isPending ? 'Adding…' : 'Add rule'}
        </button>
      </form>

      {query.isLoading && <div className="h-10 w-full animate-pulse rounded-md" style={{ background: 'var(--cc-surface-2)' }} />}
      {query.isError && <InlineError error={query.error} />}
      {query.isSuccess && query.data.length === 0 && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          No automation rules yet. Retention policy is set per-asset in the asset editor until you add one.
        </p>
      )}
      {query.isSuccess && query.data.length > 0 && (
        <>
          <ul className="flex flex-col gap-2">
            {query.data.map((rule) => (
              <li
                key={rule.policy_id}
                className="flex items-center justify-between gap-3 rounded-md px-3 py-2 text-xs"
                style={{ background: 'var(--cc-surface-2)' }}
              >
                <span>
                  <strong>{rule.name}</strong> — {rule.match_meeting_body ?? 'any'} → {rule.retention_policy}
                </span>
                <button
                  type="button"
                  onClick={() => setConfirmingRemove(rule)}
                  className="rounded-md px-2 py-1"
                  style={{ border: '1px solid var(--cc-err)', color: 'var(--cc-ink)' }}
                  aria-label={`Remove rule ${rule.name}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div>
            <button
              type="button"
              onClick={() => applyMutation.mutate()}
              disabled={applyMutation.isPending}
              className="rounded-md px-3 py-1.5 text-xs font-medium"
              style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
            >
              {applyMutation.isPending ? 'Applying…' : 'Apply rules now'}
            </button>
          </div>
        </>
      )}
      {confirmingRemove && (
        <ConfirmDialog
          title={`Remove the retention rule "${confirmingRemove.name}"?`}
          body="The rule stops applying on future runs. Assets keep the retention policy they already have."
          confirmLabel="Remove rule"
          busy={deleteMutation.isPending}
          onConfirm={() =>
            deleteMutation.mutate(confirmingRemove.policy_id, {
              onSettled: () => setConfirmingRemove(null),
            })
          }
          onCancel={() => setConfirmingRemove(null)}
        />
      )}
    </SectionCard>
  )
}

// ---------------------------------------------------------------------------
// Storage budget
// ---------------------------------------------------------------------------

function StorageBudgetSection() {
  const query = useQuery<StorageBudgetResponse, Error>({
    queryKey: ['storage-budget'],
    queryFn: getStorageBudget,
    retry: false,
  })

  return (
    <SectionCard title="Storage budget" subtitle="Media library disk usage by retention tier.">
      {query.isLoading && <div className="h-10 w-full animate-pulse rounded-md" style={{ background: 'var(--cc-surface-2)' }} />}
      {query.isError && <InlineError error={query.error} />}
      {query.isSuccess && (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold">{fmtBytes(query.data.total_bytes_used)}</span>
            {query.data.budget_bytes != null && (
              <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                of {fmtBytes(query.data.budget_bytes)} budget (
                {query.data.percent_used != null ? query.data.percent_used.toFixed(1) : '—'}%)
              </span>
            )}
            {query.data.budget_bytes == null && (
              <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                No budget configured (set CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES)
              </span>
            )}
          </div>
          {query.data.by_retention_policy.length === 0 ? (
            <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              No assets have a recorded file size yet.
            </p>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="text-left uppercase tracking-wide" style={{ color: 'var(--cc-ink-3)' }}>
                  <th className="py-1">Retention policy</th>
                  <th className="py-1">Assets</th>
                  <th className="py-1">Bytes used</th>
                </tr>
              </thead>
              <tbody>
                {query.data.by_retention_policy.map((row) => (
                  <tr key={row.retention_policy} style={{ borderTop: '1px solid var(--cc-line)' }}>
                    <td className="py-1.5">{row.retention_policy}</td>
                    <td className="py-1.5">{row.asset_count}</td>
                    <td className="cc-mono py-1.5">{fmtBytes(row.bytes_used)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </SectionCard>
  )
}

export function MediaLifecycleSettingsScreen() {
  return (
    <div className="flex flex-col">
      <header className="px-6 pb-2 pt-6">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Media Lifecycle
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Media Lifecycle Settings</h1>
        <p className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Watch folders, retention automation, and storage budget. Ingest-time readiness badges
          live on the Assets screen; missing scheduled media is under Missing Media.
        </p>
      </header>
      <WatchFolderSection />
      <RetentionPolicySection />
      <StorageBudgetSection />
    </div>
  )
}
