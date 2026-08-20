import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, createProgramSlot, listStaffAssets } from '../../api/client'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { RadioCardGroup } from '../RadioCardGroup'
import type { ProgramSlot, ProgramSlotCreate } from '../../types/api.generated'
import type { AssetRow } from '../../types/asset'

interface Props {
  channelId: string
  onClose: () => void
  onCreated: (slot: ProgramSlot) => void
}

type Recurrence = ProgramSlotCreate['recurrence']

const RECURRENCE_META: Record<Recurrence, { label: string; description: string }> = {
  once: { label: 'Once', description: 'Airs a single time at the start time.' },
  daily: { label: 'Daily', description: 'Airs every day at this time.' },
  weekly: { label: 'Weekly', description: 'Airs every week on this weekday.' },
  weekdays: { label: 'Weekdays', description: 'Airs Monday through Friday.' },
}

// Returns null rather than throwing on a value Date cannot parse.
// `toISOString()` on an Invalid Date raises RangeError, and this is called
// while building the request payload OUTSIDE handleSubmit's try/catch — so a
// throw here makes the button do nothing at all, with nothing shown to the
// operator. `submitDisabled` blocks the empty case, but a browser that falls
// back to a plain text input for `datetime-local`, or a year outside the
// representable Date range, still reaches this with unparseable text — and
// with the button disabled, handleSubmit's own validation branches never
// run. Both date fields therefore render their own inline error (matching
// ScheduleDrawer.tsx) driven directly off `firstStartUtc`/`repeatUntilInvalid`
// rather than relying on the click handler, so an inert button never ships
// without an explanation next to the field that caused it (Codex review,
// PR #427).
function localIsoToUtcIso(localIso: string): string | null {
  // Browser parses naive ISO as local time. Add tz suffix from the Date.
  const d = new Date(localIso)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

function defaultStartLocal(): string {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  // Format YYYY-MM-DDTHH:mm in local time for <input type="datetime-local">
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtClientTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function ProgramSlotDrawer({ channelId, onClose, onCreated }: Props) {
  const [assetId, setAssetId] = useState<string>('')
  const [recurrence, setRecurrence] = useState<Recurrence>('weekly')
  const [startLocal, setStartLocal] = useState<string>(() => defaultStartLocal())
  const [useAssetDuration, setUseAssetDuration] = useState(true)
  const [durationMinutes, setDurationMinutes] = useState<number>(60)
  const [titleOverride, setTitleOverride] = useState<string>('')
  const [repeatUntilLocal, setRepeatUntilLocal] = useState<string>('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const sheetRef = useRef<HTMLElement>(null)
  const headingId = 'program-slot-drawer-heading'
  const startErrorId = 'program-slot-drawer-start-error'
  const repeatUntilErrorId = 'program-slot-drawer-repeat-until-error'
  useFocusTrap(sheetRef)

  const assetsQuery = useQuery<AssetRow[], Error>({
    queryKey: ['staff-assets'],
    queryFn: listStaffAssets,
    retry: false,
  })

  const validatedAssets = useMemo(
    () => (assetsQuery.data ?? []).filter((a) => a.state === 'validated'),
    [assetsQuery.data],
  )

  const effectiveAssetId =
    assetId || (validatedAssets.length > 0 ? validatedAssets[0].asset_id : '')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const repeatable = recurrence !== 'once'
  const firstStartUtc = localIsoToUtcIso(startLocal)
  const repeatUntilUtc =
    repeatable && repeatUntilLocal ? localIsoToUtcIso(repeatUntilLocal) : null
  const repeatUntilInvalid =
    repeatable && repeatUntilLocal !== '' && repeatUntilUtc === null
  const submitDisabled =
    submitting ||
    !effectiveAssetId ||
    !startLocal ||
    firstStartUtc === null ||
    repeatUntilInvalid ||
    (!useAssetDuration && durationMinutes < 1)

  const handleSubmit = async () => {
    setSubmitError(null)
    if (firstStartUtc === null) {
      setSubmitError('Enter a start date and time before adding this slot.')
      return
    }
    if (repeatUntilInvalid) {
      setSubmitError('The repeat-until date could not be read. Re-enter it.')
      return
    }
    const payload: ProgramSlotCreate = {
      channel_id: channelId,
      asset_id: effectiveAssetId,
      recurrence,
      first_start_at: firstStartUtc,
      duration_seconds: useAssetDuration ? null : durationMinutes * 60,
      title_override: titleOverride.trim() ? titleOverride.trim() : null,
      repeat_until: repeatUntilUtc,
    }
    setSubmitting(true)
    try {
      const slot = await createProgramSlot(payload)
      onCreated(slot)
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.detail ?? `Request failed (${err.status} ${err.message}).`)
      } else if (err instanceof Error) {
        setSubmitError(err.message)
      } else {
        setSubmitError('Unknown error.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const tz = fmtClientTimezone()
  const startPreview = (() => {
    if (!startLocal) return ''
    const d = new Date(startLocal)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  })()

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
              Program guide · {channelId}
            </div>
            <h2 id={headingId} className="m-0 text-lg font-semibold tracking-tight">
              Add to guide
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close drawer"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm"
            style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <label className="mb-3 block">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Recording
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
                <strong>No validated recordings.</strong> Upload and validate a
                recording in the Assets tab first.
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
              Only validated recordings can air. The guide refreshes within the
              rolling horizon after you add a slot.
            </div>
          </label>

          <fieldset className="m-0 mb-4 border-0 p-0">
            <legend
              className="mb-2 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Repeats
            </legend>
            <RadioCardGroup
              label="Recurrence"
              options={(['once', 'daily', 'weekly', 'weekdays'] as const).map((r) => ({
                id: r,
                label: RECURRENCE_META[r].label,
                description: RECURRENCE_META[r].description,
              }))}
              value={recurrence}
              onChange={setRecurrence}
              className="grid grid-cols-2 gap-2"
            />
          </fieldset>

          <div className="mb-3 grid grid-cols-2 gap-2">
            <label className="block">
              <span
                className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: 'var(--cc-ink-3)' }}
              >
                First airing
              </span>
              <input
                type="datetime-local"
                value={startLocal}
                onChange={(e) => setStartLocal(e.target.value)}
                aria-invalid={firstStartUtc === null}
                aria-describedby={firstStartUtc === null ? startErrorId : undefined}
                className="cc-mono w-full rounded-md px-3 py-2 text-sm"
                style={{
                  background: 'var(--cc-surface)',
                  border: `1px solid ${
                    firstStartUtc === null ? 'var(--cc-danger, var(--cc-line))' : 'var(--cc-line)'
                  }`,
                  color: 'var(--cc-ink)',
                }}
              />
              {firstStartUtc === null && (
                <span
                  id={startErrorId}
                  className="mt-1 block text-xs"
                  style={{ color: 'var(--cc-danger, var(--cc-ink-2))' }}
                >
                  Enter a date and time for the first airing.
                </span>
              )}
            </label>
            {repeatable && (
              <label className="block">
                <span
                  className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  Repeat until (optional)
                </span>
                <input
                  type="datetime-local"
                  value={repeatUntilLocal}
                  onChange={(e) => setRepeatUntilLocal(e.target.value)}
                  aria-invalid={repeatUntilInvalid}
                  aria-describedby={repeatUntilInvalid ? repeatUntilErrorId : undefined}
                  className="cc-mono w-full rounded-md px-3 py-2 text-sm"
                  style={{
                    background: 'var(--cc-surface)',
                    border: `1px solid ${
                      repeatUntilInvalid ? 'var(--cc-danger, var(--cc-line))' : 'var(--cc-line)'
                    }`,
                    color: 'var(--cc-ink)',
                  }}
                />
                {repeatUntilInvalid && (
                  <span
                    id={repeatUntilErrorId}
                    className="mt-1 block text-xs"
                    style={{ color: 'var(--cc-danger, var(--cc-ink-2))' }}
                  >
                    The repeat-until date could not be read. Re-enter it.
                  </span>
                )}
              </label>
            )}
          </div>

          {startPreview && (
            <div
              className="mb-3 rounded-md p-2 text-[11px]"
              style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
            >
              {startPreview} <span className="cc-mono">({tz})</span>
            </div>
          )}

          <div className="mb-3">
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={useAssetDuration}
                onChange={(e) => setUseAssetDuration(e.target.checked)}
              />
              <span>Use the recording&apos;s own length</span>
            </label>
            {!useAssetDuration && (
              <label className="mt-2 block">
                <span
                  className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  Duration (min)
                </span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={durationMinutes}
                  onChange={(e) =>
                    setDurationMinutes(Math.max(1, Number(e.target.value) || 0))
                  }
                  className="cc-mono cc-tabular w-full rounded-md px-3 py-2 text-sm"
                  style={{
                    background: 'var(--cc-surface)',
                    border: '1px solid var(--cc-line)',
                    color: 'var(--cc-ink)',
                  }}
                />
              </label>
            )}
          </div>

          <label className="mb-3 block">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: 'var(--cc-ink-3)' }}
            >
              Guide title (optional)
            </span>
            <input
              type="text"
              value={titleOverride}
              onChange={(e) => setTitleOverride(e.target.value)}
              maxLength={200}
              placeholder="Shown to residents instead of the recording title."
              className="w-full rounded-md px-3 py-2 text-sm"
              style={{
                background: 'var(--cc-surface)',
                border: '1px solid var(--cc-line)',
                color: 'var(--cc-ink)',
              }}
            />
          </label>

          {submitError && (
            <div
              role="alert"
              className="mb-3 rounded-md p-3 text-xs"
              style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
            >
              <div className="text-sm font-semibold">Could not add to guide.</div>
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
              background: submitDisabled ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: submitDisabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
              cursor: submitDisabled ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? 'Adding…' : 'Add to guide'}
          </button>
        </footer>
      </aside>
    </div>
  )
}
