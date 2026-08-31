import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  compileAutoSchedule,
  createAutoScheduleRule,
  createSavedSearch,
  createScheduleBlock,
  deleteAutoScheduleRule,
  deleteSavedSearch,
  deleteScheduleBlock,
  getStaffIdentity,
  listAutoScheduleRules,
  listSavedSearches,
  listScheduleBlocks,
  previewAutoScheduleRule,
  updateAutoScheduleRule,
  updateSavedSearch,
  updateScheduleBlock,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type {
  AssetQuery,
  AutoScheduleRule,
  AutoScheduleRuleInput,
  RulePreview,
  SavedSearch,
  SavedSearchInput,
  ScheduleBlock,
  ScheduleBlockInput,
} from '../types/api.generated'
import {
  WEEKDAY_LABELS,
  formatDays,
  hhmmToMinute,
  minuteToHHMM,
  pickStrategyLabel,
  slotActionLabel,
  slotActionTone,
} from './autoschedule-format'
import { stateLabel } from './status-language'
import { EmptyState } from '../components/EmptyState'

type AssetStateValue = NonNullable<AssetQuery['states']>[number]

const ASSET_STATES: AssetStateValue[] = [
  'validated',
  'recorded',
  'pending_ingest',
  'ingesting',
  'rejected',
]

const MIDNIGHT_END_MINUTE = 24 * 60 // 1440 — a daypart ending exactly at midnight

const SLOT_TONE: Record<'ok' | 'muted' | 'warn', { bg: string; fg: string }> = {
  ok: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  muted: { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-2)' },
  warn: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function humanizeState(state: string): string {
  return stateLabel(state)
}

function AccessNote({ what }: { what: string }) {
  return (
    <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
      Viewing and managing {what} requires the publish operator, setup admin, or support admin role.
    </div>
  )
}

function LoadingNote({ what }: { what: string }) {
  return (
    <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
      Loading {what}…
    </div>
  )
}

const fieldStyle = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
} as const

export function ConfirmDeleteButton({
  onDelete,
  deleting,
  warning,
}: {
  onDelete: () => void
  deleting?: boolean
  warning?: string
}) {
  const [confirming, setConfirming] = useState(false)
  // Two-step: a misclick must not silently drop a saved search / daypart / rule.
  return (
    <span className="grid justify-items-end gap-1">
      <button
        type="button"
        disabled={deleting}
        onClick={() => {
          if (confirming) {
            onDelete()
            setConfirming(false)
          } else {
            setConfirming(true)
          }
        }}
        className="rounded-md px-3 py-1.5 text-xs font-semibold"
        style={{
          background: confirming ? 'var(--cc-err)' : 'var(--cc-err-soft)',
          color: confirming ? 'var(--cc-ink-inv)' : 'var(--cc-err)',
        }}
      >
        {deleting ? 'Removing...' : confirming ? 'Confirm delete?' : 'Delete'}
      </button>
      {confirming && warning && (
        <span className="max-w-[16rem] text-right text-[10px]" style={{ color: 'var(--cc-err)' }}>
          {warning}
        </span>
      )}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Saved searches (named asset queries)
// ---------------------------------------------------------------------------

export function SavedSearchForm({
  submitting,
  onSubmit,
  initial,
}: {
  submitting: boolean
  onSubmit: (payload: SavedSearchInput) => void
  initial?: SavedSearch
}) {
  const q = initial?.query
  const [name, setName] = useState(initial?.name ?? '')
  const [meetingBody, setMeetingBody] = useState(q?.meeting_body ?? '')
  const [titleContains, setTitleContains] = useState(q?.title_contains ?? '')
  const [states, setStates] = useState<string[]>(q?.states ?? ['validated', 'recorded'])
  const [minMinutes, setMinMinutes] = useState(
    q?.min_duration_seconds ? String(Math.round(q.min_duration_seconds / 60)) : '',
  )
  const [maxMinutes, setMaxMinutes] = useState(
    q?.max_duration_seconds ? String(Math.round(q.max_duration_seconds / 60)) : '',
  )
  const [orderDesc, setOrderDesc] = useState(q?.order_desc ?? true)

  const valid = name.trim().length > 0

  function buildQuery(): AssetQuery {
    const toSeconds = (v: string) => {
      const n = Number.parseInt(v, 10)
      return Number.isFinite(n) && n > 0 ? n * 60 : null
    }
    return {
      meeting_body: meetingBody.trim() === '' ? null : meetingBody.trim(),
      title_contains: titleContains.trim() === '' ? null : titleContains.trim(),
      states: states as AssetQuery['states'],
      min_duration_seconds: toSeconds(minMinutes),
      max_duration_seconds: toSeconds(maxMinutes),
      order_by: 'published_at',
      order_desc: orderDesc,
    }
  }

  return (
    <div className="grid gap-3 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Example: Recent council meetings" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Meeting body (exact)</span>
          <input value={meetingBody} onChange={(e) => setMeetingBody(e.target.value)} placeholder="Example: City Council" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs sm:col-span-2">
          <span className="font-semibold">Title contains</span>
          <input value={titleContains} onChange={(e) => setTitleContains(e.target.value)} placeholder="Example: budget" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Min length (minutes)</span>
          <input value={minMinutes} inputMode="numeric" onChange={(e) => setMinMinutes(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Max length (minutes)</span>
          <input value={maxMinutes} inputMode="numeric" onChange={(e) => setMaxMinutes(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
      </div>
      <fieldset className="grid gap-1 text-xs">
        <legend className="font-semibold">Include states</legend>
        <div className="flex flex-wrap gap-3">
          {ASSET_STATES.map((state) => (
            <label key={state} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={states.includes(state as string)}
                onChange={(e) =>
                  setStates((prev) =>
                    e.target.checked ? [...prev, state as string] : prev.filter((s) => s !== state),
                  )
                }
              />
              <span>{humanizeState(state as string)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={orderDesc} onChange={(e) => setOrderDesc(e.target.checked)} />
        <span className="font-semibold">Newest published first</span>
      </label>
      <button
        type="button"
        disabled={!valid || submitting}
        onClick={() => onSubmit({ name: name.trim(), description: initial?.description ?? null, query: buildQuery() })}
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: valid ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: valid ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {submitting ? 'Saving...' : initial ? 'Save changes' : 'Create saved search'}
      </button>
    </div>
  )
}

function SavedSearchesSection({ canWrite, canRead }: { canWrite: boolean; canRead: boolean }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['saved-searches'], queryFn: listSavedSearches, retry: false, enabled: canRead })
  // Read rules (cached) so deleting a referenced search warns instead of silently orphaning it.
  const rulesQuery = useQuery({ queryKey: ['auto-schedule-rules'], queryFn: () => listAutoScheduleRules(), retry: false, enabled: canRead })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['saved-searches'] })
  const create = useMutation({
    mutationFn: (payload: SavedSearchInput) => createSavedSearch(payload),
    onSuccess: () => {
      void invalidate()
      setCreating(false)
    },
  })
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SavedSearchInput }) => updateSavedSearch(id, payload),
    onSuccess: () => {
      void invalidate()
      setEditingId(null)
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteSavedSearch(id),
    onSuccess: () => void invalidate(),
  })
  const searches = query.data ?? []
  const rules = rulesQuery.data ?? []
  const error = create.error ?? update.error ?? remove.error
  const referencedWarning = (id: string): string | undefined => {
    const count = rules.filter((r) => r.saved_search_id === id).length
    return count > 0 ? `Used by ${count} rule${count > 1 ? 's' : ''} — deleting it stops them scheduling.` : undefined
  }
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Saved searches</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Named queries over your library. A rule fills its daypart by picking from one of these.
          </p>
        </div>
        {canWrite && (
          <button type="button" onClick={() => setCreating((v) => !v)} className="rounded-md px-3 py-2 text-sm font-semibold" style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}>
            {creating ? 'Close' : 'Add saved search'}
          </button>
        )}
      </div>
      {!canRead ? (
        <AccessNote what="saved searches" />
      ) : (
        <>
          {error != null && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(error, 'The saved search could not be saved.')}
            </div>
          )}
          {creating && canWrite && <SavedSearchForm submitting={create.isPending} onSubmit={(p) => create.mutate(p)} />}
          {query.isLoading && <LoadingNote what="saved searches" />}
          {!query.isLoading && searches.length === 0 && (
            <EmptyState
              headline="No saved searches yet."
              body="A saved search collects the recordings that match rules you set — the newest council meetings, a weekly series, a category. Create one here and auto-schedule uses it to pick what airs."
            />
          )}
          <div className="grid gap-2">
            {searches.map((search: SavedSearch) => (
              <article key={search.saved_search_id} className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="m-0 text-sm font-semibold">{search.name}</h3>
                    <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                      {search.query?.meeting_body ? `Body: ${search.query.meeting_body}` : 'Any body'}
                      {search.query?.title_contains ? ` · title ~ "${search.query.title_contains}"` : ''}
                    </p>
                  </div>
                  {canWrite && (
                    <div className="flex items-start gap-2">
                      <button type="button" onClick={() => setEditingId((id) => (id === search.saved_search_id ? null : search.saved_search_id))} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                        {editingId === search.saved_search_id ? 'Close' : 'Edit'}
                      </button>
                      <ConfirmDeleteButton onDelete={() => remove.mutate(search.saved_search_id)} deleting={remove.isPending} warning={referencedWarning(search.saved_search_id)} />
                    </div>
                  )}
                </div>
                {editingId === search.saved_search_id && canWrite && (
                  <SavedSearchForm
                    initial={search}
                    submitting={update.isPending}
                    onSubmit={(payload) => update.mutate({ id: search.saved_search_id, payload })}
                  />
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Daypart blocks
// ---------------------------------------------------------------------------

export function BlockForm({
  submitting,
  onSubmit,
  initial,
}: {
  submitting: boolean
  onSubmit: (payload: ScheduleBlockInput) => void
  initial?: ScheduleBlock
}) {
  const [channel, setChannel] = useState(initial?.channel_id ?? '')
  const [name, setName] = useState(initial?.name ?? '')
  const [start, setStart] = useState(initial ? minuteToHHMM(initial.start_minute) : '18:00')
  // A daypart ending exactly at midnight is stored as 1440; <input type=time>
  // can't render 24:00, so show/accept "00:00" and map it on submit.
  const [end, setEnd] = useState(
    initial ? (initial.end_minute === MIDNIGHT_END_MINUTE ? '00:00' : minuteToHHMM(initial.end_minute)) : '22:00',
  )
  const [days, setDays] = useState<number[]>(initial?.days_of_week ?? [0, 1, 2, 3, 4])

  const valid = channel.trim().length > 0 && name.trim().length > 0 && days.length > 0

  return (
    <div className="grid gap-3 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Channel</span>
          <input value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="public" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Prime time" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Start</span>
          <input type="time" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">End</span>
          <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
          <span style={{ color: 'var(--cc-ink-3)' }}>00:00 = midnight (end of day). An end before the start wraps past midnight.</span>
        </label>
      </div>
      <fieldset className="grid gap-1 text-xs">
        <legend className="font-semibold">Days</legend>
        <div className="flex flex-wrap gap-3">
          {WEEKDAY_LABELS.map((label, index) => (
            <label key={label} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={days.includes(index)}
                onChange={(e) => setDays((prev) => (e.target.checked ? [...prev, index] : prev.filter((d) => d !== index)))}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <button
        type="button"
        disabled={!valid || submitting}
        onClick={() =>
          onSubmit({
            channel_id: channel.trim(),
            name: name.trim(),
            start_minute: hhmmToMinute(start),
            end_minute: end === '00:00' ? MIDNIGHT_END_MINUTE : hhmmToMinute(end),
            days_of_week: [...days].sort((a, b) => a - b),
            active_from: initial?.active_from ?? null,
            active_until: initial?.active_until ?? null,
            enabled: initial?.enabled ?? true,
          })
        }
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: valid ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: valid ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {submitting ? 'Saving...' : initial ? 'Save changes' : 'Create daypart'}
      </button>
    </div>
  )
}

function BlocksSection({ canWrite, canRead }: { canWrite: boolean; canRead: boolean }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['schedule-blocks'], queryFn: () => listScheduleBlocks(), retry: false, enabled: canRead })
  const rulesQuery = useQuery({ queryKey: ['auto-schedule-rules'], queryFn: () => listAutoScheduleRules(), retry: false, enabled: canRead })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['schedule-blocks'] })
  const create = useMutation({
    mutationFn: (payload: ScheduleBlockInput) => createScheduleBlock(payload),
    onSuccess: () => {
      void invalidate()
      setCreating(false)
    },
  })
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ScheduleBlockInput }) => updateScheduleBlock(id, payload),
    onSuccess: () => {
      void invalidate()
      setEditingId(null)
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => deleteScheduleBlock(id), onSuccess: () => void invalidate() })
  const blocks = query.data ?? []
  const rules = rulesQuery.data ?? []
  const error = create.error ?? update.error ?? remove.error
  const referencedWarning = (id: string): string | undefined => {
    const count = rules.filter((r) => r.schedule_block_id === id).length
    return count > 0 ? `Used by ${count} rule${count > 1 ? 's' : ''} — deleting it stops them scheduling.` : undefined
  }
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Dayparts</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Recurring time windows on a channel that a rule fills (e.g. weeknights 6–10pm). Times are the station's
            local wall-clock (set by CIVICCAST_STATION_TZ; UTC if unset).
          </p>
        </div>
        {canWrite && (
          <button type="button" onClick={() => setCreating((v) => !v)} className="rounded-md px-3 py-2 text-sm font-semibold" style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}>
            {creating ? 'Close' : 'Add daypart'}
          </button>
        )}
      </div>
      {!canRead ? (
        <AccessNote what="dayparts" />
      ) : (
        <>
          {error != null && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(error, 'The daypart could not be saved.')}
            </div>
          )}
          {creating && canWrite && <BlockForm submitting={create.isPending} onSubmit={(p) => create.mutate(p)} />}
          {query.isLoading && <LoadingNote what="dayparts" />}
          {!query.isLoading && blocks.length === 0 && (
            <EmptyState
              headline="No dayparts yet."
              body="A daypart is a block of air time you hand over to auto-schedule — weekday evenings, overnight repeats. Create one here and rules can start filling it."
            />
          )}
          <div className="grid gap-2">
            {blocks.map((block: ScheduleBlock) => (
              <article key={block.block_id} className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="m-0 text-sm font-semibold">{block.name}</h3>
                    <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                      {block.channel_id} · {minuteToHHMM(block.start_minute)}–{minuteToHHMM(block.end_minute)} · {formatDays(block.days_of_week ?? [])}
                    </p>
                  </div>
                  {canWrite && (
                    <div className="flex items-start gap-2">
                      <button type="button" onClick={() => setEditingId((id) => (id === block.block_id ? null : block.block_id))} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                        {editingId === block.block_id ? 'Close' : 'Edit'}
                      </button>
                      <ConfirmDeleteButton onDelete={() => remove.mutate(block.block_id)} deleting={remove.isPending} warning={referencedWarning(block.block_id)} />
                    </div>
                  )}
                </div>
                {editingId === block.block_id && canWrite && (
                  <BlockForm
                    initial={block}
                    submitting={update.isPending}
                    onSubmit={(payload) => update.mutate({ id: block.block_id, payload })}
                  />
                )}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Rules (bind a saved search to a daypart) + simulate
// ---------------------------------------------------------------------------

export function RulePreviewPanel({ preview }: { preview: RulePreview }) {
  if (preview.missing_dependency) {
    return (
      <div role="status" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
        This rule points at a saved search or daypart that no longer exists.
      </div>
    )
  }
  const slots = preview.slots ?? []
  return (
    <div className="grid gap-2">
      <p className="m-0 text-xs font-semibold">
        Would schedule {preview.would_fill_count ?? 0} of {slots.length} upcoming slots.
      </p>
      <div className="grid gap-1">
        {slots.slice(0, 30).map((slot, index) => {
          const colors = SLOT_TONE[slotActionTone(slot.action)]
          return (
            <div key={index} className="flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-1 text-xs" style={{ background: 'var(--cc-surface-2)' }}>
              <span>{new Date(slot.starts_at).toLocaleString()}</span>
              <span className="flex items-center gap-2">
                {slot.title && <span style={{ color: 'var(--cc-ink-2)' }}>{slot.title}</span>}
                <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase" style={{ background: colors.bg, color: colors.fg }}>
                  {slotActionLabel(slot.action)}
                </span>
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RuleCard({
  rule,
  searches,
  blocks,
  canWrite,
  editing,
  onEdit,
  onDelete,
  deleting,
}: {
  rule: AutoScheduleRule
  searches: SavedSearch[]
  blocks: ScheduleBlock[]
  canWrite: boolean
  editing: boolean
  onEdit: () => void
  onDelete: (id: string) => void
  deleting: boolean
}) {
  const preview = useMutation({ mutationFn: (id: string) => previewAutoScheduleRule(id) })
  const searchName = searches.find((s) => s.saved_search_id === rule.saved_search_id)?.name ?? rule.saved_search_id
  const blockName = blocks.find((b) => b.block_id === rule.schedule_block_id)?.name ?? rule.schedule_block_id
  return (
    <article className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="m-0 text-sm font-semibold">{rule.name}</h3>
            {rule.enabled === false && (
              <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
                disabled
              </span>
            )}
          </div>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {rule.channel_id} · “{searchName}” → “{blockName}” · {pickStrategyLabel(rule.pick_strategy)} · {rule.rolling_window_days ?? 30}d window
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" disabled={preview.isPending} onClick={() => preview.mutate(rule.rule_id)} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
            {preview.isPending ? 'Simulating...' : 'Simulate'}
          </button>
          {canWrite && (
            <button type="button" onClick={onEdit} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}>
              {editing ? 'Close' : 'Edit'}
            </button>
          )}
          {canWrite && <ConfirmDeleteButton onDelete={() => onDelete(rule.rule_id)} deleting={deleting} />}
        </div>
      </div>
      {preview.error && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(preview.error, 'Simulation failed.')}
        </div>
      )}
      {preview.data && <RulePreviewPanel preview={preview.data} />}
    </article>
  )
}

export function RuleForm({
  searches,
  blocks,
  submitting,
  onSubmit,
  initial,
}: {
  searches: SavedSearch[]
  blocks: ScheduleBlock[]
  submitting: boolean
  onSubmit: (payload: AutoScheduleRuleInput) => void
  initial?: AutoScheduleRule
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [savedSearchId, setSavedSearchId] = useState(initial?.saved_search_id ?? '')
  const [blockId, setBlockId] = useState(initial?.schedule_block_id ?? '')
  const [pickStrategy, setPickStrategy] = useState<'top_result' | 'random_result' | 'newest'>(
    initial?.pick_strategy ?? 'newest',
  )
  const [windowDays, setWindowDays] = useState(String(initial?.rolling_window_days ?? 30))
  const [repeatDays, setRepeatDays] = useState(String(initial?.repeat_prevention_days ?? 0))

  const block = blocks.find((b) => b.block_id === blockId)
  const windowValid = Number.isFinite(Number(windowDays)) && Number(windowDays) >= 14 && Number(windowDays) <= 60
  const valid = name.trim().length > 0 && savedSearchId !== '' && blockId !== '' && windowValid

  return (
    <div className="grid gap-3 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Fill prime with council" className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Pick strategy</span>
          <select value={pickStrategy} onChange={(e) => setPickStrategy(e.target.value as typeof pickStrategy)} className="rounded-md px-2 py-1.5" style={fieldStyle}>
            <option value="newest">Newest first</option>
            <option value="top_result">First match</option>
            <option value="random_result">Random</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Saved search</span>
          <select value={savedSearchId} onChange={(e) => setSavedSearchId(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle}>
            <option value="">Choose…</option>
            {searches.map((s) => (
              <option key={s.saved_search_id} value={s.saved_search_id}>{s.name}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Daypart</span>
          <select value={blockId} onChange={(e) => setBlockId(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle}>
            <option value="">Choose…</option>
            {blocks.map((b) => (
              <option key={b.block_id} value={b.block_id}>{b.name} ({b.channel_id})</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">Rolling window (days, 14–60)</span>
          <input value={windowDays} inputMode="numeric" aria-invalid={!windowValid} onChange={(e) => setWindowDays(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span className="font-semibold">No-repeat window (days)</span>
          <input value={repeatDays} inputMode="numeric" onChange={(e) => setRepeatDays(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        {!windowValid && (
          <span className="text-xs sm:col-span-2" style={{ color: 'var(--cc-err)' }}>
            Rolling window must be a whole number from 14 to 60 days.
          </span>
        )}
      </div>
      {block == null && blockId !== '' && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>Daypart not found.</p>
      )}
      <button
        type="button"
        disabled={!valid || submitting}
        onClick={() =>
          onSubmit({
            name: name.trim(),
            saved_search_id: savedSearchId,
            channel_id: block?.channel_id ?? '',
            schedule_block_id: blockId,
            pick_strategy: pickStrategy,
            rolling_window_days: Number(windowDays),
            repeat_prevention_days: Math.max(0, Number(repeatDays) || 0),
            priority: initial?.priority ?? 100,
            enabled: initial?.enabled ?? true,
          })
        }
        className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
        style={{ background: valid ? 'var(--cc-ink)' : 'var(--cc-surface-3)', color: valid ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)' }}
      >
        {submitting ? 'Saving...' : initial ? 'Save changes' : 'Create rule'}
      </button>
    </div>
  )
}

function RulesSection({ canWrite, canRead }: { canWrite: boolean; canRead: boolean }) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const rulesQuery = useQuery({ queryKey: ['auto-schedule-rules'], queryFn: () => listAutoScheduleRules(), retry: false, enabled: canRead })
  const searchesQuery = useQuery({ queryKey: ['saved-searches'], queryFn: listSavedSearches, retry: false, enabled: canRead })
  const blocksQuery = useQuery({ queryKey: ['schedule-blocks'], queryFn: () => listScheduleBlocks(), retry: false, enabled: canRead })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['auto-schedule-rules'] })
  const create = useMutation({
    mutationFn: (payload: AutoScheduleRuleInput) => createAutoScheduleRule(payload),
    onSuccess: () => {
      void invalidate()
      setCreating(false)
    },
  })
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: AutoScheduleRuleInput }) => updateAutoScheduleRule(id, payload),
    onSuccess: () => {
      void invalidate()
      setEditingId(null)
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => deleteAutoScheduleRule(id), onSuccess: () => void invalidate() })
  const rules = rulesQuery.data ?? []
  const searches = searchesQuery.data ?? []
  const blocks = blocksQuery.data ?? []
  const error = create.error ?? update.error ?? remove.error
  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Auto-schedule rules</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Each rule fills a daypart from a saved search. Simulate to preview; rules feed the commit gate before air.
          </p>
        </div>
        {canWrite && (
          <button type="button" onClick={() => setCreating((v) => !v)} className="rounded-md px-3 py-2 text-sm font-semibold" style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}>
            {creating ? 'Close' : 'Add rule'}
          </button>
        )}
      </div>
      {!canRead ? (
        <AccessNote what="auto-schedule rules" />
      ) : (
        <>
          {error != null && (
            <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(error, 'The rule could not be saved.')}
            </div>
          )}
          {creating && canWrite && <RuleForm searches={searches} blocks={blocks} submitting={create.isPending} onSubmit={(p) => create.mutate(p)} />}
          {rulesQuery.isLoading && <LoadingNote what="rules" />}
          {!rulesQuery.isLoading && rules.length === 0 && (
            <EmptyState
              headline="No rules yet."
              body="A rule connects a saved search to a daypart so the channel fills itself with matching programs. Create a saved search and a daypart first, then add a rule here to connect them."
            />
          )}
          <div className="grid gap-2">
            {rules.map((rule: AutoScheduleRule) => (
              <div key={rule.rule_id} className="grid gap-2">
                <RuleCard
                  rule={rule}
                  searches={searches}
                  blocks={blocks}
                  canWrite={canWrite}
                  editing={editingId === rule.rule_id}
                  onEdit={() => setEditingId((id) => (id === rule.rule_id ? null : rule.rule_id))}
                  deleting={remove.isPending && remove.variables === rule.rule_id}
                  onDelete={(id) => remove.mutate(id)}
                />
                {editingId === rule.rule_id && canWrite && (
                  <RuleForm
                    searches={searches}
                    blocks={blocks}
                    initial={rule}
                    submitting={update.isPending}
                    onSubmit={(payload) => update.mutate({ id: rule.rule_id, payload })}
                  />
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

function CompileBar({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient()
  const compile = useMutation({
    mutationFn: () => compileAutoSchedule(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auto-schedule-rules'] }),
  })
  if (!canWrite) return null
  const report = compile.data
  return (
    <section className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Compile schedule</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Run every enabled rule and add its picks to the schedule. The new items still need an operator commit before they air.
          </p>
        </div>
        <button type="button" disabled={compile.isPending} onClick={() => compile.mutate()} className="rounded-md px-3 py-2 text-sm font-semibold" style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}>
          {compile.isPending ? 'Compiling...' : 'Compile now'}
        </button>
      </div>
      {compile.error && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(compile.error, 'Compile failed.')}
        </div>
      )}
      {report && (
        <div role="status" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}>
          Added {report.items_created ?? 0} scheduled items across {report.results?.length ?? 0} rules.
        </div>
      )}
    </section>
  )
}

export function AutoScheduleScreen() {
  const identityQuery = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity, retry: false })
  // Fail CLOSED: writes/compile need publish_operator or setup_admin (the same
  // gate the router enforces); reads also allow support_admin.
  const canWrite =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'publish_operator') || hasOperatorRole(identityQuery.data, 'setup_admin'))
  const canRead =
    canWrite || (identityQuery.isSuccess && hasOperatorRole(identityQuery.data, 'support_admin'))
  return (
    <div className="grid gap-6 px-6 py-5">
      <header>
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Run Meeting
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Auto-schedule</h1>
        <p className="m-0 mt-1 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Define saved searches and dayparts, connect them with rules, then preview and compile to fill the
          schedule automatically. Compiling a rule approves its picked items to air &mdash; reviewing the
          preview before you compile is the approval step. Only manually-added schedule items need a separate
          Commit-to-Air approval.
        </p>
      </header>
      <SavedSearchesSection canWrite={canWrite} canRead={canRead} />
      <BlocksSection canWrite={canWrite} canRead={canRead} />
      <RulesSection canWrite={canWrite} canRead={canRead} />
      <CompileBar canWrite={canWrite} />
    </div>
  )
}
