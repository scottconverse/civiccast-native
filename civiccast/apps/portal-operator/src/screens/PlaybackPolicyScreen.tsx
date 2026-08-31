import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  getPlaybackPolicy,
  getPlaybackPolicyAuditLog,
  updatePlaybackPolicy,
} from '../api/client'
import type {
  PlaybackPolicyConfig,
  PlaybackPolicyUpdate,
  PrerollCreative,
} from '../types/api.generated'
import { EmptyState } from '../components/EmptyState'

type SubjectType = PlaybackPolicyConfig['subject_type']
type AccessTier = NonNullable<PlaybackPolicyConfig['access_tier']>
type CreativeKind = PrerollCreative['kind']

interface CreativeDraft {
  creative_id: string
  kind: CreativeKind
  asset_url: string
  duration_seconds: string
  skippable_after_seconds: string
  accessible_label: string
  transcript_url: string
}

interface PolicyFormState {
  access_tier: AccessTier
  invite_group_id: string
  oidc_provider_id: string
  authenticated_rss_enabled: boolean
  public_record_required: boolean
  public_archive_complete: boolean
  preroll_enabled: boolean
  creatives: CreativeDraft[]
}

const EMPTY_CREATIVE: CreativeDraft = {
  creative_id: '',
  kind: 'graphic',
  asset_url: '',
  duration_seconds: '10',
  skippable_after_seconds: '',
  accessible_label: '',
  transcript_url: '',
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function defaultState(): PolicyFormState {
  return {
    access_tier: 'public',
    invite_group_id: '',
    oidc_provider_id: '',
    authenticated_rss_enabled: false,
    public_record_required: false,
    public_archive_complete: false,
    preroll_enabled: false,
    creatives: [
      { ...EMPTY_CREATIVE, creative_id: 'station-card', accessible_label: 'Station announcement' },
    ],
  }
}

function stateFromPolicy(policy: PlaybackPolicyConfig): PolicyFormState {
  const creatives = policy.preroll?.creatives?.length
    ? policy.preroll.creatives.map((creative) => ({
        creative_id: creative.creative_id,
        kind: creative.kind,
        asset_url: creative.asset_url,
        duration_seconds: String(creative.duration_seconds),
        skippable_after_seconds: creative.skippable_after_seconds == null
          ? ''
          : String(creative.skippable_after_seconds),
        accessible_label: creative.accessible_label,
        transcript_url: creative.transcript_url ?? '',
      }))
    : defaultState().creatives
  return {
    access_tier: policy.access_tier ?? 'public',
    invite_group_id: policy.invite_group_id ?? '',
    oidc_provider_id: policy.oidc_provider_id ?? '',
    authenticated_rss_enabled: policy.authenticated_rss_enabled ?? false,
    public_record_required: policy.public_record_required ?? false,
    public_archive_complete: policy.public_archive_complete ?? false,
    preroll_enabled: policy.preroll?.enabled ?? false,
    creatives,
  }
}

function buildUpdate(state: PolicyFormState): PlaybackPolicyUpdate {
  const gated = state.access_tier !== 'public'
  const creatives = state.creatives
    .filter((creative) => (
      creative.creative_id.trim() &&
      creative.asset_url.trim() &&
      creative.accessible_label.trim()
    ))
    .map((creative) => ({
      creative_id: creative.creative_id.trim(),
      kind: creative.kind,
      asset_url: creative.asset_url.trim(),
      duration_seconds: Number(creative.duration_seconds || 0),
      skippable_after_seconds: creative.skippable_after_seconds
        ? Number(creative.skippable_after_seconds)
        : null,
      accessible_label: creative.accessible_label.trim(),
      transcript_url: creative.transcript_url.trim() || null,
    }))

  return {
    access_tier: state.access_tier,
    invite_group_id: state.access_tier === 'invite_only' ? state.invite_group_id.trim() : null,
    oidc_provider_id: gated && state.oidc_provider_id.trim() ? state.oidc_provider_id.trim() : null,
    authenticated_rss_enabled: gated ? state.authenticated_rss_enabled : false,
    public_record_required: state.public_record_required,
    public_archive_complete: state.public_archive_complete,
    preroll: {
      enabled: state.preroll_enabled,
      creatives: state.preroll_enabled ? creatives : [],
      apply_to_archive_exports: false,
    },
  }
}

// `Intl.DateTimeFormat.format()` THROWS RangeError on an Invalid Date. The
// falsy check catches null/undefined/'' but not an unparseable string, and
// this renders audit-log rows — one bad row would blank the entire log.
function formatDate(value: string | null | undefined): string {
  if (!value) return 'Never'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return 'Unreadable date'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-[11px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
      {children}
    </label>
  )
}

function TextInput({
  label,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  placeholder?: string
}) {
  return (
    <div className="grid gap-1.5">
      <FieldLabel>{label}</FieldLabel>
      <input
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md px-3 py-2 text-sm"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
      />
    </div>
  )
}

function CheckboxRow({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <label
      className="flex items-center gap-2 rounded-md px-3 py-2 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  )
}

function Segment<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: Array<{ value: T; label: string }>
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="grid gap-1.5">
      <FieldLabel>{label}</FieldLabel>
      <div className="flex flex-wrap gap-1" role="tablist" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={value === option.value}
            onClick={() => onChange(option.value)}
            className="rounded-md px-3 py-2 text-xs font-semibold"
            style={{
              background: value === option.value ? 'var(--cc-brand-soft)' : 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: value === option.value ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function CreativeEditor({
  creative,
  index,
  onChange,
  onRemove,
}: {
  creative: CreativeDraft
  index: number
  onChange: (creative: CreativeDraft) => void
  onRemove: () => void
}) {
  return (
    <div
      className="grid gap-3 rounded-md p-3"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold">Preroll {index + 1}</div>
        <button
          type="button"
          onClick={onRemove}
          className="rounded-md px-2 py-1 text-xs font-semibold"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          Remove
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <TextInput
          label="Creative ID"
          value={creative.creative_id}
          onChange={(value) => onChange({ ...creative, creative_id: value })}
        />
        <Segment<CreativeKind>
          label="Kind"
          value={creative.kind}
          onChange={(value) => onChange({ ...creative, kind: value })}
          options={[
            { value: 'graphic', label: 'Graphic' },
            { value: 'video', label: 'Video' },
          ]}
        />
        <TextInput
          label="Asset URL"
          value={creative.asset_url}
          placeholder="/media/preroll/station-card.png"
          onChange={(value) => onChange({ ...creative, asset_url: value })}
        />
        <TextInput
          label="Accessible label"
          value={creative.accessible_label}
          onChange={(value) => onChange({ ...creative, accessible_label: value })}
        />
        <TextInput
          label="Duration seconds"
          value={creative.duration_seconds}
          onChange={(value) => onChange({ ...creative, duration_seconds: value.replace(/\D/g, '') })}
        />
        <TextInput
          label="Skip after seconds"
          value={creative.skippable_after_seconds}
          onChange={(value) => onChange({
            ...creative,
            skippable_after_seconds: value.replace(/\D/g, ''),
          })}
        />
        <TextInput
          label="Transcript URL"
          value={creative.transcript_url}
          onChange={(value) => onChange({ ...creative, transcript_url: value })}
        />
      </div>
    </div>
  )
}

export function PlaybackPolicyScreen() {
  const queryClient = useQueryClient()
  const [subjectType, setSubjectType] = useState<SubjectType>('channel')
  const [subjectId, setSubjectId] = useState('government')
  const [form, setForm] = useState<PolicyFormState>(() => defaultState())
  const normalizedSubjectId = subjectId.trim() || 'government'

  const policyQuery = useQuery({
    queryKey: ['playback-policy', subjectType, normalizedSubjectId],
    queryFn: () => getPlaybackPolicy(subjectType, normalizedSubjectId),
  })
  const auditQuery = useQuery({
    queryKey: ['playback-policy-audit'],
    queryFn: getPlaybackPolicyAuditLog,
  })
  const saveMutation = useMutation({
    mutationFn: () => updatePlaybackPolicy(subjectType, normalizedSubjectId, buildUpdate(form)),
    onSuccess: (policy) => {
      setForm(stateFromPolicy(policy))
      queryClient.setQueryData(['playback-policy', subjectType, normalizedSubjectId], policy)
      void queryClient.invalidateQueries({ queryKey: ['playback-policy-audit'] })
    },
  })

  useEffect(() => {
    if (!policyQuery.data) return undefined
    const handle = window.setTimeout(() => setForm(stateFromPolicy(policyQuery.data)), 0)
    return () => window.clearTimeout(handle)
  }, [policyQuery.data])

  const saveDisabled = useMemo(() => {
    if (saveMutation.isPending) return true
    if (form.access_tier === 'invite_only' && !form.invite_group_id.trim()) return true
    if (form.preroll_enabled) {
      return !form.creatives.some((creative) => (
        creative.creative_id.trim() &&
        creative.asset_url.trim() &&
        creative.accessible_label.trim() &&
        Number(creative.duration_seconds) > 0
      ))
    }
    return false
  }, [form, saveMutation.isPending])
  const policy = policyQuery.data
  const auditEvents = auditQuery.data?.events ?? []

  return (
    <div className="grid gap-5 px-6 py-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">Playback policy</h1>
          <div className="mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Access gates, public-record locks, prerolls, and decision audit.
          </div>
        </div>
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveDisabled}
          className="rounded-md px-4 py-2 text-sm font-semibold"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {saveMutation.isPending ? 'Saving' : 'Save policy'}
        </button>
      </div>

      {(policyQuery.error || saveMutation.error) && (
        <div
          role="alert"
          className="rounded-md p-3 text-sm"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-ink)' }}
        >
          {apiMessage(policyQuery.error ?? saveMutation.error, 'Playback policy request failed.')}
        </div>
      )}

      <section
        className="grid gap-4 rounded-md p-4"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        <div className="grid gap-3 md:grid-cols-[220px_minmax(220px,1fr)_auto]">
          <Segment<SubjectType>
            label="Policy target"
            value={subjectType}
            onChange={setSubjectType}
            options={[
              { value: 'channel', label: 'Channel' },
              { value: 'asset', label: 'Asset' },
            ]}
          />
          <TextInput label="Target ID" value={subjectId} onChange={setSubjectId} />
          <div className="self-end rounded-md px-3 py-2 text-xs" style={{ background: 'var(--cc-surface)' }}>
            Updated {formatDate(policy?.updated_at)}
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <div className="grid gap-3">
            <Segment<AccessTier>
              label="Access tier"
              value={form.access_tier}
              onChange={(value) => setForm((current) => ({ ...current, access_tier: value }))}
              options={[
                { value: 'public', label: 'Public' },
                { value: 'authenticated', label: 'Authenticated' },
                { value: 'invite_only', label: 'Invite only' },
              ]}
            />
            <div className="grid gap-3 md:grid-cols-2">
              <TextInput
                label="Invite group"
                value={form.invite_group_id}
                disabled={form.access_tier !== 'invite_only'}
                onChange={(value) => setForm((current) => ({ ...current, invite_group_id: value }))}
              />
              <TextInput
                label="OIDC provider"
                value={form.oidc_provider_id}
                disabled={form.access_tier === 'public'}
                onChange={(value) => setForm((current) => ({ ...current, oidc_provider_id: value }))}
              />
            </div>
          </div>

          <div className="grid content-start gap-2">
            <CheckboxRow
              label="Authenticated RSS"
              checked={form.authenticated_rss_enabled}
              disabled={form.access_tier === 'public'}
              onChange={(checked) => setForm((current) => ({
                ...current,
                authenticated_rss_enabled: checked,
              }))}
            />
            <CheckboxRow
              label="Public-record asset"
              checked={form.public_record_required}
              onChange={(checked) => setForm((current) => ({
                ...current,
                public_record_required: checked,
                access_tier: checked ? 'public' : current.access_tier,
                authenticated_rss_enabled: checked ? false : current.authenticated_rss_enabled,
              }))}
            />
            <CheckboxRow
              label="Public archive complete"
              checked={form.public_archive_complete}
              onChange={(checked) => setForm((current) => ({
                ...current,
                public_archive_complete: checked,
                access_tier: checked ? 'public' : current.access_tier,
                authenticated_rss_enabled: checked ? false : current.authenticated_rss_enabled,
              }))}
            />
          </div>
        </div>
      </section>

      <section
        className="grid gap-3 rounded-md p-4"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CheckboxRow
            label="Preroll enabled"
            checked={form.preroll_enabled}
            onChange={(checked) => setForm((current) => ({ ...current, preroll_enabled: checked }))}
          />
          <button
            type="button"
            disabled={!form.preroll_enabled || form.creatives.length >= 4}
            onClick={() => setForm((current) => ({
              ...current,
              creatives: [
                ...current.creatives,
                { ...EMPTY_CREATIVE, creative_id: `preroll-${current.creatives.length + 1}` },
              ],
            }))}
            className="rounded-md px-3 py-2 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Add preroll
          </button>
        </div>
        {form.preroll_enabled && (
          <div className="grid gap-3">
            {form.creatives.map((creative, index) => (
              <CreativeEditor
                key={`${index}-${creative.creative_id}`}
                creative={creative}
                index={index}
                onRemove={() => setForm((current) => ({
                  ...current,
                  creatives: current.creatives.filter((_, itemIndex) => itemIndex !== index),
                }))}
                onChange={(next) => setForm((current) => ({
                  ...current,
                  creatives: current.creatives.map((item, itemIndex) => (
                    itemIndex === index ? next : item
                  )),
                }))}
              />
            ))}
          </div>
        )}
      </section>

      <section
        className="grid gap-3 rounded-md p-4"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="m-0 text-sm font-semibold">Decision audit</h2>
          <button
            type="button"
            onClick={() => void auditQuery.refetch()}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Refresh
          </button>
        </div>
        {auditQuery.error && (
          <div className="text-sm" style={{ color: 'var(--cc-err)' }}>
            {apiMessage(auditQuery.error, 'Audit log request failed.')}
          </div>
        )}
        {auditEvents.length === 0 ? (
          <EmptyState
            headline="No playback decisions yet."
            body="Every time the player allows or blocks a viewer under this policy, the decision is logged here. Decisions appear as soon as residents start watching."
          />
        ) : (
          <div className="grid gap-2">
            {auditEvents.slice(-8).reverse().map((event) => (
              <div
                key={event.event_id}
                className="grid gap-2 rounded-md p-3 md:grid-cols-[1fr_auto]"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
              >
                <div>
                  <div className="text-sm font-semibold">
                    {event.asset_id} / {event.channel_id}
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                    {event.reason}
                  </div>
                  {event.preroll_creative_ids.length > 0 && (
                    <div className="cc-mono mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                      Preroll: {event.preroll_creative_ids.join(', ')}
                    </div>
                  )}
                </div>
                <div className="text-right text-xs">
                  <div
                    className="rounded-full px-2 py-0.5 font-semibold uppercase"
                    style={{
                      background: event.decision === 'allowed' ? 'var(--cc-ok-soft)' : 'var(--cc-err-soft)',
                    }}
                  >
                    {event.decision}
                  </div>
                  <div className="cc-mono mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                    {formatDate(event.occurred_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
