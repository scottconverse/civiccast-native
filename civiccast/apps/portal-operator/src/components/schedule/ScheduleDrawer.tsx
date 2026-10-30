import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ApiError,
  createSchedule,
  getStationTimeZone,
  listChannelProfiles,
  listStaffAssets,
} from '../../api/client'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import {
  dateToStationDateTimeLocal,
  effectiveStationTimeZone,
  formatStationInstant,
  stationWallClockToDate,
} from '../../lib/station-time'
import { RadioCardGroup } from '../RadioCardGroup'
import type {
  ScheduleConflictDetail,
  ScheduleItem,
  ScheduleItemCreate,
  ScheduleMode,
} from '../../types/schedule'
import { MODE_META } from '../../types/schedule'
import type { AssetRow } from '../../types/asset'
import type { ChannelProfile } from '../../types/api.generated'

interface Props {
  onClose: () => void
  onCreated: (item: ScheduleItem) => void
}

// Channel options come from the station's real cable channels
// (/api/staff/cable/channels) — the same ids the playout/commit-to-air lane
// keys on. A hardcoded numbered demo list here shipped in rc3 and
// severed schedule→air: programs were written to channel ids the commit
// panel could never see (clean-VM gauntlet finding F-RC3-6).

function defaultStartLocal(timeZone: string): string {
  const nextHour = new Date((Math.floor(Date.now() / 3_600_000) + 1) * 3_600_000)
  return dateToStationDateTimeLocal(nextHour, timeZone)
}

export function ScheduleDrawer({ onClose, onCreated }: Props) {
  const stationProfileQuery = useQuery({
    queryKey: ['station-timezone'],
    queryFn: getStationTimeZone,
    retry: false,
  })
  const timeZone = effectiveStationTimeZone(stationProfileQuery.data?.station_timezone)
  const defaultStart = useMemo(() => defaultStartLocal(timeZone), [timeZone])
  const [mode, setMode] = useState<ScheduleMode>('premiere')
  const [assetId, setAssetId] = useState<string>('')
  const [channelId, setChannelId] = useState<string>('')
  const [startLocalOverride, setStartLocalOverride] = useState<string | null>(null)
  const startLocal = startLocalOverride ?? defaultStart
  const [durationMinutes, setDurationMinutes] = useState<number>(60)
  const [durationSeconds, setDurationSeconds] = useState<number>(0)
  const totalDurationSeconds = durationMinutes * 60 + durationSeconds
  const [notes, setNotes] = useState<string>('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [conflictItem, setConflictItem] = useState<ScheduleConflictDetail | null>(
    null,
  )
  const [submitting, setSubmitting] = useState(false)
  const sheetRef = useRef<HTMLElement>(null)
  const headingId = 'schedule-drawer-heading'
  const startErrorId = 'schedule-drawer-start-error'
  useFocusTrap(sheetRef)

  const assetsQuery = useQuery<AssetRow[], Error>({
    queryKey: ['staff-assets'],
    queryFn: listStaffAssets,
    retry: false,
  })

  const channelsQuery = useQuery<ChannelProfile[], Error>({
    queryKey: ['channel-profiles'],
    queryFn: listChannelProfiles,
    retry: false,
  })

  const channelOptions = useMemo(
    () =>
      (channelsQuery.data ?? []).map((profile) => ({
        id: profile.channel_id,
        label: profile.branding.display_name,
      })),
    [channelsQuery.data],
  )

  // Same compute-during-render default as effectiveAssetId below.
  const effectiveChannelId =
    channelId || (channelOptions.length > 0 ? channelOptions[0].id : '')

  const validatedAssets = useMemo(
    () => (assetsQuery.data ?? []).filter((a) => a.state === 'validated'),
    [assetsQuery.data],
  )

  // Default the asset selection to the first validated asset once the list
  // resolves. Computing this during render (instead of in an effect) avoids
  // the cascading-render anti-pattern flagged by react-hooks/set-state-in-effect.
  const effectiveAssetId =
    assetId || (validatedAssets.length > 0 ? validatedAssets[0].asset_id : '')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const requiresDuration = mode !== 'embargo'
  const startInstant = stationWallClockToDate(startLocal, timeZone)
  const startAtUtc = startInstant?.toISOString() ?? null
  const submitDisabled =
    submitting ||
    stationProfileQuery.isLoading ||
    stationProfileQuery.isError ||
    !effectiveAssetId ||
    !effectiveChannelId ||
    startAtUtc === null ||
    (requiresDuration && totalDurationSeconds < 1)

  const handleSubmit = async () => {
    setSubmitError(null)
    setConflictItem(null)
    if (stationProfileQuery.isLoading || stationProfileQuery.isError) {
      setSubmitError('Could not load the station timezone. Close this drawer and retry after the station profile is available.')
      return
    }
    if (startAtUtc === null) {
      setSubmitError(
        mode === 'embargo'
          ? 'Enter a release date and time before scheduling.'
          : 'Enter a start date and time before scheduling.',
      )
      return
    }
    const payload: ScheduleItemCreate = {
      asset_id: effectiveAssetId,
      channel_id: effectiveChannelId,
      mode,
      scheduled_at: startAtUtc,
      duration_seconds: requiresDuration ? totalDurationSeconds : null,
      notes: notes.trim() ? notes.trim() : null,
    }
    setSubmitting(true)
    try {
      const item = await createSchedule(payload)
      onCreated(item)
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.conflict) {
          setConflictItem(err.conflict)
        } else {
          setSubmitError(
            err.detail ?? `Request failed (${err.status} ${err.message}).`,
          )
        }
      } else if (err instanceof Error) {
        setSubmitError(err.message)
      } else {
        setSubmitError('Unknown error.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const startPreview = startInstant
    ? formatStationInstant(startInstant, timeZone, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
    : ''

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      className="fixed inset-0 z-50 flex"
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <button
        type="button"
        aria-label="Close drawer backdrop"
        onClick={onClose}
        className="flex-1"
        style={{ background: 'transparent' }}
      />
      <aside
        ref={sheetRef}
        tabIndex={-1}
        className="flex h-full w-full max-w-md flex-col outline-none"
        style={{
          background: 'var(--cc-surface)',
          borderLeft: '1px solid var(--cc-line)',
        }}
      >
        <header
          className="flex items-start justify-between gap-2 px-5 py-4"
          style={{ borderBottom: '1px solid var(--cc-line)' }}
        >
          <div>
            <div
              className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Schedule
            </div>
            <h2
              id={headingId}
              className="m-0 text-lg font-semibold tracking-tight"
            >
              New scheduled item
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close drawer"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm"
            style={{
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink-2)',
            }}
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <fieldset className="m-0 mb-4 border-0 p-0">
            <legend
              className="mb-2 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Mode
            </legend>
            <RadioCardGroup
              label="Schedule mode"
              options={(['premiere', 'embargo'] as const).map((m) => ({
                id: m,
                label: MODE_META[m].label,
                description: MODE_META[m].description,
              }))}
              value={mode}
              onChange={setMode}
              className="grid grid-cols-2 gap-2"
            />
          </fieldset>

          <label className="mb-3 block">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Asset
            </span>
            {assetsQuery.isLoading ? (
              <div
                className="h-9 w-full animate-pulse rounded-md"
                style={{ background: 'var(--cc-surface-2)' }}
              />
            ) : validatedAssets.length === 0 ? (
              <div
                className="rounded-md p-3 text-xs"
                style={{
                  background: 'var(--cc-warn-soft)',
                  color: 'var(--cc-ink)',
                  border: '1px solid var(--cc-line)',
                }}
              >
                <strong>No validated assets.</strong> Upload and validate an asset
                in the Assets tab first.
              </div>
            ) : (
              <select
                value={effectiveAssetId}
                onChange={(e) => setAssetId(e.target.value)}
                className="w-full rounded-md px-3 py-2 text-sm"
                style={{
                  background: 'var(--cc-surface)',
                  border: '1px solid var(--cc-line)',
                  color: 'var(--cc-ink)',
                }}
              >
                {validatedAssets.map((a) => (
                  <option key={a.asset_id} value={a.asset_id}>
                    {a.title} · {a.asset_id}
                  </option>
                ))}
              </select>
            )}
            <div className="mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              Only validated assets are eligible. Trim and chapter edits are
              applied at packaging time.
            </div>
          </label>

          <label className="mb-3 block">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Channel
            </span>
            <select
              value={effectiveChannelId}
              onChange={(e) => setChannelId(e.target.value)}
              disabled={channelOptions.length === 0}
              className="w-full rounded-md px-3 py-2 text-sm"
              style={{
                background: 'var(--cc-surface)',
                border: '1px solid var(--cc-line)',
                color: 'var(--cc-ink)',
              }}
            >
              {channelOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
            {channelsQuery.isError ? (
              <span
                role="alert"
                className="mt-1 block text-xs"
                style={{ color: 'var(--cc-danger, #b91c1c)' }}
              >
                Could not load this station's channels. Close and retry.
              </span>
            ) : channelOptions.length === 0 && !channelsQuery.isLoading ? (
              <span className="mt-1 block text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                No channels are configured on this station yet.
              </span>
            ) : null}
          </label>

          <div className="mb-3 grid grid-cols-2 gap-2">
            <label className="block">
              <span
                className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: 'var(--cc-ink-3)' }}
              >
              {mode === 'embargo' ? 'Release at' : 'Start at'} (station time: {timeZone})
              </span>
              <input
                type="datetime-local"
                step={1}
                value={startLocal}
                onChange={(e) => {
                  setStartLocalOverride(e.target.value)
                }}
                aria-invalid={startAtUtc === null}
                aria-describedby={startAtUtc === null ? startErrorId : undefined}
                className="cc-mono w-full rounded-md px-3 py-2 text-sm"
                style={{
                  background: 'var(--cc-surface)',
                  border: `1px solid ${
                    startAtUtc === null ? 'var(--cc-danger, var(--cc-line))' : 'var(--cc-line)'
                  }`,
                  color: 'var(--cc-ink)',
                }}
              />
              {startAtUtc === null && (
                <span
                  id={startErrorId}
                  className="mt-1 block text-xs"
                  style={{ color: 'var(--cc-danger, var(--cc-ink-2))' }}
                >
                  {startLocal
                    ? `That station time does not exist during the spring clock change, or the value is invalid. Choose another time in ${timeZone}.`
                    : 'Enter a date and time to schedule this.'}
                </span>
              )}
            </label>
            {requiresDuration && (
              <div className="block"><label className="block">
                <span
                  className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  Duration minutes
                </span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  aria-label="Duration minutes"
                  value={durationMinutes}
                  onChange={(e) =>
                    setDurationMinutes(Math.max(0, Math.floor(Number(e.target.value) || 0)))
                  }
                  className="cc-mono cc-tabular w-full rounded-md px-3 py-2 text-sm"
                  style={{
                    background: 'var(--cc-surface)',
                    border: '1px solid var(--cc-line)',
                    color: 'var(--cc-ink)',
                  }}
                />
                </label><label className="mt-2 block"><span className="block text-xs">Additional seconds (0–59)</span>
                <input
                  aria-label="Duration seconds"
                  type="number"
                  min={0}
                  max={59}
                  step={1}
                  value={durationSeconds}
                  onChange={(e) => setDurationSeconds(Math.min(59, Math.max(0, Math.floor(Number(e.target.value) || 0))))}
                  className="cc-mono cc-tabular w-full rounded-md px-3 py-2 text-sm"
                />
                {totalDurationSeconds < 1 && <span role="alert">Enter a duration of at least one second.</span>}
              </label></div>
            )}
          </div>

          {startPreview && (
            <div
              className="mb-3 rounded-md p-2 text-[11px]"
              style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
            >
              {startPreview} <span className="cc-mono">({timeZone})</span>
            </div>
          )}

          {stationProfileQuery.isError && (
            <div role="alert" className="mb-3 rounded-md p-2 text-[11px]" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              Could not load the station timezone. Close this drawer and retry after the station profile is available.
            </div>
          )}

          <div
            className="mb-3 rounded-md p-2 text-[11px]"
            style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink-2)' }}
          >
            <strong style={{ color: 'var(--cc-ink)' }}>Station time ({timeZone}):</strong>{' '}
            a time skipped by the spring clock change cannot be scheduled. A repeated fall-back time uses its earlier occurrence.
          </div>

          <label className="mb-3 block">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Notes (optional)
            </span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Operator notes — visible in the audit log."
              className="w-full rounded-md px-3 py-2 text-sm"
              style={{
                background: 'var(--cc-surface)',
                border: '1px solid var(--cc-line)',
                color: 'var(--cc-ink)',
              }}
            />
          </label>

          {conflictItem && (
            <div
              role="alert"
              className="mb-3 rounded-md p-3 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              <div className="text-sm font-semibold">Time slot conflicts.</div>
              <div className="mt-1" style={{ color: 'var(--cc-ink-2)' }}>
                {conflictItem.message}
              </div>
              <div
                className="cc-mono mt-2 rounded-md p-2 text-[11px]"
                style={{ background: 'var(--cc-surface)', color: 'var(--cc-ink-2)' }}
              >
                Existing: <strong>{conflictItem.conflicting_item.asset_id}</strong>{' '}
                on <strong>{conflictItem.conflicting_item.channel_id}</strong>{' '}
                at{' '}
                {new Date(
                  conflictItem.conflicting_item.scheduled_at,
                ).toLocaleString(undefined, {
                  timeZone,
                  hour: 'numeric',
                  minute: '2-digit',
                  month: 'short',
                  day: 'numeric',
                })}
              </div>
              <div className="mt-2" style={{ color: 'var(--cc-ink-2)' }}>
                <strong>Next step.</strong> Pick a different time, channel, or
                cancel the conflicting item.
              </div>
            </div>
          )}

          {submitError && (
            <div
              role="alert"
              className="mb-3 rounded-md p-3 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              <div className="text-sm font-semibold">Could not schedule.</div>
              <div className="mt-1" style={{ color: 'var(--cc-ink-2)' }}>
                {submitError}
              </div>
            </div>
          )}
        </div>

        <footer
          className="flex items-center justify-end gap-2 px-5 py-3"
          style={{ borderTop: '1px solid var(--cc-line)' }}
        >
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitDisabled}
            className="rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{
              background: submitDisabled
                ? 'var(--cc-surface-3)'
                : 'var(--cc-brand)',
              color: submitDisabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
              cursor: submitDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting
              ? 'Scheduling…'
              : mode === 'premiere'
                ? 'Schedule premiere'
                : 'Schedule embargo'}
          </button>
        </footer>
      </aside>
    </div>
  )
}
