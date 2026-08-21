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
} from '../api/client'
import { useToast } from '../components/toast-context'
import type {
  AssetRetentionPolicyResponse,
  StorageBudgetResponse,
  WatchFolderConfigResponse,
} from '../types/api.generated'

const RETENTION_POLICIES = ['default', 'permanent', 'meeting', 'short'] as const

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
  return (
    <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
      {isApiError && error.detail ? error.detail : `Request failed: ${error.message}`}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Watch folders
// ---------------------------------------------------------------------------

function WatchFolderSection() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [monitorPath, setMonitorPath] = useState('')
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
          type="submit"
          disabled={!monitorPath.trim() || createMutation.isPending}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {createMutation.isPending ? 'Adding…' : 'Add watch folder'}
        </button>
      </form>

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
              <div className="flex items-center gap-2">
                <span style={{ color: config.enabled ? 'var(--cc-ok)' : 'var(--cc-ink-3)' }}>
                  {config.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate(config.config_id)}
                  className="rounded-md px-2 py-1"
                  style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-err)' }}
                  aria-label={`Remove watch folder ${config.monitor_path}`}
                >
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ul>
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
                  onClick={() => deleteMutation.mutate(rule.policy_id)}
                  className="rounded-md px-2 py-1"
                  style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-err)' }}
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
