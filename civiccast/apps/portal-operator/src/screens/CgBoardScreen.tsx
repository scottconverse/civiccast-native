import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createCgBulletin,
  getAppPlatformConfig,
  getCgPortalDisplay,
  getStaffBulletinQueue,
  getStaffIdentity,
  moderateCgBulletin,
} from '../api/client'
import type {
  BulletinUpdate,
  CgBulletinSubmission,
  CgPortalDisplay,
  CgTemplate,
  CgTemplateZone,
  CgZone,
} from '../types/api.generated'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../components/toast-context'

const POLL_MS = 30_000

const panelStyle = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
}

const insetStyle = {
  background: 'var(--cc-surface-2)',
  border: '1px solid var(--cc-line)',
}

type Region = CgTemplateZone['region']
type ZoneKind = CgTemplateZone['zone_kind']

const REGION_LABELS: Record<Region, string> = {
  main: 'Main',
  lower: 'Lower',
  side: 'Side',
  bug: 'Bug',
  background: 'Background',
}

const REGION_AREAS: Record<Region, string> = {
  background: '1 / 1 / 4 / 5',
  main: '1 / 1 / 3 / 4',
  side: '1 / 4 / 3 / 5',
  lower: '3 / 1 / 4 / 5',
  bug: '1 / 4 / 2 / 5',
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function contentLabel(zone: CgZone | undefined): string {
  if (!zone) return 'Unassigned'
  const headline = zone.content?.headline
  const body = zone.content?.body
  const items = zone.content?.items
  if (typeof headline === 'string') return headline
  if (typeof body === 'string') return body
  if (Array.isArray(items)) return `${items.length} items`
  return zone.title ?? zone.zone_id
}

function zonesByKind(display: CgPortalDisplay | undefined): Map<ZoneKind, CgZone> {
  return new Map((display?.snapshot.zones ?? []).map((zone) => [zone.kind, zone]))
}

function TemplateButton({
  template,
  active,
  onSelect,
}: {
  template: CgTemplate
  active: boolean
  onSelect: (templateId: string) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onSelect(template.template_id)}
      className="grid min-h-24 min-w-0 gap-2 rounded-md p-3 text-left"
      style={{
        ...insetStyle,
        borderColor: active ? 'var(--cc-brand)' : 'var(--cc-line)',
        background: active ? 'var(--cc-brand-soft)' : 'var(--cc-surface-2)',
      }}
    >
      <span className="text-sm font-semibold">{template.label}</span>
      <span className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
        {template.regions.length} regions / {template.aspect_ratio}
      </span>
    </button>
  )
}

export function LayoutPreview({
  template,
  display,
}: {
  template: CgTemplate | undefined
  display: CgPortalDisplay | undefined
}) {
  const zoneMap = useMemo(() => zonesByKind(display), [display])
  const regionsByName = useMemo(() => {
    const grouped = new Map<Region, CgTemplateZone[]>()
    for (const region of template?.regions ?? []) {
      grouped.set(region.region, [...(grouped.get(region.region) ?? []), region])
    }
    for (const [region, zones] of grouped) {
      grouped.set(region, [...zones].sort((a, b) => a.order - b.order))
    }
    return grouped
  }, [template?.regions])
  return (
    <section className="min-w-0 overflow-hidden rounded-md p-4" style={panelStyle}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Visual layout editor</h2>
          <div className="cc-mono text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {template?.template_id ?? 'Loading template…'}
          </div>
        </div>
        <span
          className="cc-mono max-w-full truncate rounded-full px-2 py-1 text-[11px]"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}
        >
          {display?.snapshot.proof_boundary ?? 'Loading…'}
        </span>
      </div>
      <div
        className="relative mt-4 grid aspect-video min-h-80 min-w-0 gap-2 overflow-hidden rounded-md p-3"
        style={{
          ...insetStyle,
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gridTemplateRows: '1fr 1fr 1.25fr',
        }}
      >
        {[...regionsByName.entries()].map(([regionName, regionZones]) => {
          return (
            <div
              key={regionName}
              className="grid min-h-0 gap-2 overflow-hidden rounded-md p-3"
              style={{
                gridArea: REGION_AREAS[regionName],
                background:
                  regionName === 'background'
                    ? 'var(--cc-surface)'
                    : 'var(--cc-brand-soft)',
                border: '1px solid var(--cc-line-strong)',
                zIndex: regionName === 'background' ? 0 : 1,
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-semibold">{REGION_LABELS[regionName]}</span>
                <span className="cc-mono rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: 'var(--cc-surface)', color: 'var(--cc-ink-2)' }}>
                  {regionZones.map((zone) => zone.zone_kind).join(' + ')}
                </span>
              </div>
              <div className="grid min-h-0 gap-2 overflow-auto">
                {regionZones.map((regionZone) => {
                  const zone = zoneMap.get(regionZone.zone_kind)
                  return (
                    <div
                      key={`${regionName}-${regionZone.zone_kind}`}
                      className="min-w-0 rounded-md p-2"
                      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
                    >
                      <div className="min-w-0 text-sm font-semibold">{contentLabel(zone)}</div>
                      <div className="cc-mono mt-1 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                        {regionZone.zone_kind} / {zone?.source ?? 'source-pending'}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

const BULLETIN_STATE_TONE: Record<
  CgBulletinSubmission['state'],
  { bg: string; fg: string; label: string }
> = {
  submitted: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-info)', label: 'Submitted' },
  needs_changes: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-warn)', label: 'Needs changes' },
  accepted: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)', label: 'Approved' },
  scheduled: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ok)', label: 'Scheduled' },
  declined: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-3)', label: 'Declined' },
}

function BulletinAddForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean
  onSubmit: (draft: {
    organization: string
    submitter_label: string
    title: string
    message: string
  }) => void
}) {
  const [organization, setOrganization] = useState('')
  const [submitterLabel, setSubmitterLabel] = useState('')
  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const disabled =
    submitting || !organization.trim() || !submitterLabel.trim() || !title.trim() || !message.trim()
  return (
    <div className="grid gap-2 rounded-md p-3" style={insetStyle}>
      <div className="text-xs font-semibold">Add a bulletin</div>
      {(
        [
          ['Organization', organization, setOrganization],
          ['Submitted by', submitterLabel, setSubmitterLabel],
          ['Title', title, setTitle],
        ] as const
      ).map(([label, value, setter]) => (
        <label key={label} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>{label}</span>
          <input
            type="text"
            value={value}
            onChange={(e) => setter(e.target.value)}
            className="rounded-md px-2 py-1.5 text-sm outline-none"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
      ))}
      <label className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Message</span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={2}
          className="rounded-md px-2 py-1.5 text-sm outline-none"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
        />
      </label>
      <div>
        <button
          type="button"
          disabled={disabled}
          onClick={() =>
            onSubmit({
              organization: organization.trim(),
              submitter_label: submitterLabel.trim(),
              title: title.trim(),
              message: message.trim(),
            })
          }
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{
            background: disabled ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
            color: disabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
          }}
        >
          {submitting ? 'Adding…' : 'Add bulletin'}
        </button>
      </div>
    </div>
  )
}

// In-app replacement for window.prompt when requesting changes or declining
// a bulletin — the native browser prompt breaks the app's webview theming.
// A blank submission never silently no-ops: it toasts and keeps the dialog
// open so the operator can fix it, matching the ConfirmDialog's escape/focus
// contract without pulling in its confirm/cancel button pair.
function ModerationNoteDialog({
  title,
  placeholder,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  title: string
  placeholder: string
  submitLabel: string
  onSubmit: (notes: string) => void
  onCancel: () => void
}) {
  const [notes, setNotes] = useState('')
  const toast = useToast()
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const onCancelRef = useRef(onCancel)
  useEffect(() => {
    onCancelRef.current = onCancel
  }, [onCancel])

  useEffect(() => {
    textareaRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCancelRef.current()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [])

  const submit = () => {
    const trimmed = notes.trim()
    if (!trimmed) {
      toast.push({ tone: 'error', message: 'Enter a note before submitting — it tells the submitter what to fix.' })
      return
    }
    onSubmit(trimmed)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'color-mix(in srgb, var(--cc-ink) 45%, transparent)' }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="moderation-note-title"
        className="grid w-full max-w-md gap-3 rounded-md p-5"
        style={{
          background: 'var(--cc-surface)',
          border: '1px solid var(--cc-line)',
          boxShadow: '0 12px 32px rgba(0, 0, 0, 0.35)',
        }}
      >
        <h2 id="moderation-note-title" className="m-0 text-base font-semibold">
          {title}
        </h2>
        <textarea
          ref={textareaRef}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder={placeholder}
          rows={4}
          className="rounded-md px-3 py-2 text-sm"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
        />
        <div className="mt-1 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-2 text-sm font-medium"
            style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

export function BulletinModerationPanel({ channelId }: { channelId: string }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showAdd, setShowAdd] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingModeration, setPendingModeration] = useState<
    { kind: 'changes' | 'decline'; submission: CgBulletinSubmission } | null
  >(null)

  const queueQuery = useQuery({
    queryKey: ['staff-bulletins', channelId],
    queryFn: () => getStaffBulletinQueue(channelId),
    refetchInterval: POLL_MS,
    retry: false,
  })
  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['staff-bulletins', channelId] })
    void queryClient.invalidateQueries({ queryKey: ['cg-portal-display'] })
  }

  const createMutation = useMutation({
    mutationFn: (draft: {
      organization: string
      submitter_label: string
      title: string
      message: string
    }) => createCgBulletin(channelId, draft),
    onSuccess: () => {
      setShowAdd(false)
      setActionError(null)
      refresh()
    },
    onError: (err) => setActionError(apiMessage(err, 'Could not add the bulletin.')),
  })

  const moderateMutation = useMutation({
    mutationFn: ({ submissionId, patch }: { submissionId: string; patch: BulletinUpdate }) =>
      moderateCgBulletin(channelId, submissionId, patch),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (err) => setActionError(apiMessage(err, 'Could not update the bulletin.')),
  })

  const submissions = queueQuery.data?.submissions ?? []
  const busy = createMutation.isPending || moderateMutation.isPending
  const operatorId = identityQuery.data?.operator_id

  const approve = (submission: CgBulletinSubmission) => {
    if (!operatorId) {
      setActionError('Your staff identity has not loaded yet — try again in a moment.')
      return
    }
    moderateMutation.mutate({
      submissionId: submission.submission_id,
      patch: { state: 'accepted', approved_by_operator: operatorId },
    })
  }

  const requestChanges = (submission: CgBulletinSubmission) => {
    setPendingModeration({ kind: 'changes', submission })
  }

  const decline = (submission: CgBulletinSubmission) => {
    setPendingModeration({ kind: 'decline', submission })
  }

  return (
    <section className="min-w-0 rounded-md p-4" style={panelStyle} aria-label="Community bulletins">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-lg font-semibold">Community bulletins</h2>
        <button
          type="button"
          onClick={() => setShowAdd((v) => !v)}
          className="rounded-md px-2.5 py-1 text-xs font-semibold"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {showAdd ? 'Close' : 'Add bulletin'}
        </button>
      </div>
      <div className="mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
        Approved bulletins air as branded filler slides between programs on
        channels set to “Community bulletins”.
      </div>

      {queueQuery.isError && (
        <div role="alert" className="mt-3 rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(queueQuery.error, 'Could not load the bulletin queue.')}
        </div>
      )}

      <div className="mt-3 grid gap-2">
        {showAdd && (
          <BulletinAddForm
            submitting={createMutation.isPending}
            onSubmit={(draft) => createMutation.mutate(draft)}
          />
        )}

        {queueQuery.isSuccess && submissions.length === 0 && (
          <EmptyState
            headline="No bulletins yet."
            body="The community board runs station and community announcements on this channel between programs. Add the first bulletin above to get it started."
          />
        )}

        {submissions.map((submission) => {
          const tone = BULLETIN_STATE_TONE[submission.state]
          const moderatable =
            submission.state === 'submitted' || submission.state === 'needs_changes'
          return (
            <div key={submission.submission_id} className="rounded-md p-3 text-sm" style={insetStyle}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold">{submission.title}</span>
                <span
                  className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                  style={{ background: tone.bg, color: tone.fg }}
                >
                  {tone.label}
                </span>
              </div>
              <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                {submission.organization} · {submission.submitter_label}
              </div>
              <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                {submission.message}
              </div>
              {submission.moderation_notes && (
                <div className="mt-1 text-[11px]" style={{ color: 'var(--cc-warn)' }}>
                  Notes: {submission.moderation_notes}
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                {moderatable && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => approve(submission)}
                    className="rounded-md px-2.5 py-1 text-[11px] font-semibold"
                    style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ok)', border: '1px solid var(--cc-ok)' }}
                  >
                    Approve
                  </button>
                )}
                {moderatable && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => requestChanges(submission)}
                    className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                    style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
                  >
                    Request changes
                  </button>
                )}
                {submission.state !== 'declined' && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => decline(submission)}
                    className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                    style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-err)', background: 'var(--cc-surface)' }}
                  >
                    Decline
                  </button>
                )}
              </div>
            </div>
          )
        })}

        {actionError && (
          <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
            {actionError}
          </div>
        )}
      </div>

      {pendingModeration && (
        <ModerationNoteDialog
          title={pendingModeration.kind === 'changes' ? 'Request changes' : 'Decline bulletin'}
          placeholder={
            pendingModeration.kind === 'changes'
              ? 'What needs to change before this bulletin can air?'
              : 'Why is this bulletin declined? (Required.)'
          }
          submitLabel={pendingModeration.kind === 'changes' ? 'Send request' : 'Decline bulletin'}
          onSubmit={(notes) => {
            moderateMutation.mutate({
              submissionId: pendingModeration.submission.submission_id,
              patch:
                pendingModeration.kind === 'changes'
                  ? { state: 'needs_changes', moderation_notes: notes }
                  : { state: 'declined', moderation_notes: notes },
            })
            setPendingModeration(null)
          }}
          onCancel={() => {
            toast.push({
              tone: 'info',
              message:
                pendingModeration.kind === 'changes'
                  ? 'Request changes cancelled — no note was sent.'
                  : 'Decline cancelled — the bulletin was not declined.',
            })
            setPendingModeration(null)
          }}
        />
      )}
    </section>
  )
}

function FeedPanel({ display }: { display: CgPortalDisplay | undefined }) {
  const adapters = display?.feed_catalog.adapters ?? []
  return (
    <section className="min-w-0 rounded-md p-4" style={panelStyle}>
      <h2 className="m-0 text-lg font-semibold">Dynamic feeds</h2>
      <div className="mt-3 grid gap-2">
        {adapters.map((adapter) => (
          <div key={adapter.adapter_id} className="rounded-md p-3 text-sm" style={insetStyle}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{adapter.label}</span>
              <span className="cc-mono rounded-full px-1.5 py-0.5 text-[10px]" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                {adapter.kind}
              </span>
            </div>
            <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              {adapter.source_url}
            </div>
            <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              {adapter.target_zone_kinds.join(', ')} / refresh {Math.round(adapter.refresh_seconds / 60)} min
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function OutputPanel({ display }: { display: CgPortalDisplay | undefined }) {
  return (
    <section className="min-w-0 rounded-md p-4" style={panelStyle}>
      <h2 className="m-0 text-lg font-semibold">Output paths</h2>
      <div className="mt-3 grid gap-2 text-sm">
        <div className="rounded-md p-3" style={insetStyle}>
          <div className="font-semibold">Portal display</div>
          <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {display?.snapshot.portal_render_path ?? 'Loading…'}
          </div>
        </div>
        <div className="rounded-md p-3" style={insetStyle}>
          <div className="font-semibold">HLS channel output</div>
          <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {display?.render_plan.manifest_url ?? 'Loading…'}
          </div>
        </div>
        <div className="rounded-md p-3" style={insetStyle}>
          <div className="font-semibold">Overlay contract</div>
          <div className="cc-mono mt-1 break-all text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {display?.render_plan.linear_overlay_contract_url ?? 'Loading…'}
          </div>
        </div>
      </div>
    </section>
  )
}

export function CgBoardScreen() {
  const [channelId, setChannelId] = useState('public')
  const [templateId, setTemplateId] = useState<string | undefined>(undefined)
  const appConfigQuery = useQuery({
    queryKey: ['app-platform-config'],
    queryFn: getAppPlatformConfig,
    refetchInterval: POLL_MS,
  })
  const displayQuery = useQuery({
    queryKey: ['cg-portal-display', channelId, templateId],
    queryFn: () => getCgPortalDisplay(channelId, templateId),
    refetchInterval: POLL_MS,
  })
  const display = displayQuery.data
  const templates = display?.template_library.templates ?? []
  const activeTemplateId = templateId ?? display?.template_library.active_template_id
  const activeTemplate = templates.find((template) => template.template_id === activeTemplateId)
  const channels = appConfigQuery.data?.channels ?? []
  const error = appConfigQuery.error ?? displayQuery.error

  return (
    <div className="grid min-w-0 gap-5 overflow-x-hidden px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">CG Board</h1>
          <p className="m-0 mt-1 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Build the between-streams board, live ticker, schedule zones, and streaming output contract.
          </p>
        </div>
        <label className="grid gap-1 text-sm" htmlFor="cg-channel">
          <span className="font-semibold">Channel</span>
          <select
            id="cg-channel"
            value={channelId}
            onChange={(event) => {
              setChannelId(event.target.value)
              setTemplateId(undefined)
            }}
            className="rounded-md px-3 py-2 text-sm outline-none"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          >
            <option value="public">Public board</option>
            {channels.map((channel) => (
              <option key={channel.channel_id} value={channel.channel_id}>
                {channel.branding.display_name}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && (
        <div role="alert" className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}>
          {apiMessage(error, 'CG board could not load.')}
        </div>
      )}

      <section className="grid min-w-0 gap-3 md:grid-cols-3" aria-label="Template library">
        {templates.map((template) => (
          <TemplateButton
            key={template.template_id}
            template={template}
            active={template.template_id === activeTemplateId}
            onSelect={setTemplateId}
          />
        ))}
      </section>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <LayoutPreview template={activeTemplate} display={display} />
        <div className="grid min-w-0 content-start gap-4">
          <OutputPanel display={display} />
          <FeedPanel display={display} />
          <BulletinModerationPanel channelId={channelId} />
        </div>
      </div>
    </div>
  )
}
