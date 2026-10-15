import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getStaffIdentity } from '../api/client'
import {
  applyStationImport,
  listStationImportBatches,
  previewStationImport,
  rollbackStationImport,
} from '../api/stationImport'
import type { ImportBatch, ImportPlan, StaffIdentityResponse } from '../types/api.generated'
import { manualLink } from './manual-link'

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'The import request could not be completed.'
}

function ImportResult({ batch }: { batch: ImportBatch }) {
  return (
    <section aria-label="Import result" className="rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)' }}>
      <h2 className="mt-0 text-lg font-semibold">{batch.status === 'rolled_back' ? 'Import rolled back' : 'Import completed'}</h2>
      <p className="text-sm">Batch {batch.import_batch_id}: {batch.shows_created ?? 0} shows and {batch.schedule_items_created ?? 0} schedule entries created.</p>
      {(batch.apply_failures ?? []).length > 0 && (
        <div role="alert">
          <h3 className="text-base font-semibold">Rows that could not be imported</h3>
          <ul>{batch.apply_failures?.map((failure, index) => (
            <li key={`${failure.kind}-${failure.source_ref}-${index}`}>{failure.kind} {failure.source_ref}: {failure.reason}</li>
          ))}</ul>
        </div>
      )}
    </section>
  )
}

export function StationImportScreen() {
  const identity = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  if (identity.isPending) return <p role="status" className="p-6">Loading staff access…</p>
  if (identity.isError) return <p role="alert" className="p-6">Could not check staff access. {message(identity.error)}</p>
  if (!identity.data.roles?.includes('setup_admin')) {
    return <p role="alert" className="p-6">Station import requires a setup administrator.</p>
  }
  return <StationImportBody />
}

function StationImportBody() {
  const queryClient = useQueryClient()
  const [baseUrl, setBaseUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [plan, setPlan] = useState<ImportPlan | null>(null)
  const [reviewed, setReviewed] = useState(false)
  const [result, setResult] = useState<ImportBatch | null>(null)
  const [rollbackId, setRollbackId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const batches = useQuery({ queryKey: ['station-import-batches'], queryFn: listStationImportBatches })

  const invalidatePreview = () => {
    setPlan(null)
    setReviewed(false)
    setResult(null)
    setError(null)
  }

  const preview = useMutation({
    mutationFn: previewStationImport,
    onSuccess: (nextPlan) => {
      setPlan(nextPlan)
      setReviewed(false)
      setResult(null)
      setPassword('')
      setError(null)
    },
    onError: (failure) => setError(message(failure)),
  })
  const apply = useMutation({
    mutationFn: applyStationImport,
    onSuccess: (batch) => {
      setResult(batch)
      setPlan(null) // The same plan must not be submitted twice accidentally.
      setReviewed(false)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['station-import-batches'] })
    },
    onError: (failure) => {
      setError(`${message(failure)} Check batch history before trying Apply again; the server may have committed some rows.`)
      void queryClient.invalidateQueries({ queryKey: ['station-import-batches'] })
    },
  })
  const rollback = useMutation({
    mutationFn: rollbackStationImport,
    onSuccess: (batch) => {
      setResult(batch)
      setRollbackId(null)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['station-import-batches'] })
    },
    onError: (failure) => setError(message(failure)),
  })

  const busy = preview.isPending || apply.isPending || rollback.isPending
  const shows = plan?.shows_to_create ?? []
  const schedule = plan?.schedule_items_to_create ?? []
  const conflicts = plan?.conflicts ?? []
  const skipped = plan?.skipped ?? []

  return (
    <main className="mx-auto grid max-w-5xl gap-6 p-6" aria-labelledby="station-import-title">
      <header>
        <p className="m-0 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--cc-ink-3)' }}>Station setup</p>
        <h1 id="station-import-title" className="mb-1 mt-1 text-2xl font-semibold">Import from Cablecast</h1>
        <p className="m-0 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Preview existing show and schedule metadata before adding it to CivicCast. This does not copy media files.
          The source password is used for this preview only and is not saved here.
        </p>
        <Link to={manualLink('station-import-cablecast')} style={{ color: 'var(--cc-brand)' }}>How station import works</Link>
      </header>

      {error && <p role="alert" className="rounded-md p-3" style={{ background: 'var(--cc-err-soft)' }}>{error}</p>}
      {busy && <p role="status">{preview.isPending ? 'Connecting to Cablecast and comparing records…' : apply.isPending ? `Importing ${shows.length} shows and ${schedule.length} schedule entries…` : 'Rolling back the selected batch…'}</p>}

      <section className="grid gap-3 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)' }}>
        <h2 className="m-0 text-lg font-semibold">Source connection</h2>
        <label htmlFor="cablecast-url">Cablecast API URL</label>
        <input id="cablecast-url" type="url" required disabled={busy} placeholder="https://station.example/cablecastapi/v1" value={baseUrl}
          onChange={(event) => { setBaseUrl(event.target.value); invalidatePreview() }} className="w-full rounded border p-2" />
        <label htmlFor="cablecast-user">Username (if required)</label>
        <input id="cablecast-user" autoComplete="username" disabled={busy} value={username}
          onChange={(event) => { setUsername(event.target.value); invalidatePreview() }} className="w-full rounded border p-2" />
        <label htmlFor="cablecast-password">Password (if required)</label>
        <input id="cablecast-password" type="password" autoComplete="off" disabled={busy} value={password}
          onChange={(event) => { setPassword(event.target.value); invalidatePreview() }} className="w-full rounded border p-2" />
        <div><button type="button" disabled={busy || !baseUrl.trim()} onClick={() => {
          const url = baseUrl.trim()
          try {
            if (!['http:', 'https:'].includes(new URL(url).protocol)) throw new Error('Use an HTTP or HTTPS Cablecast API URL.')
          } catch { setError('Enter a full HTTP or HTTPS Cablecast API URL.'); return }
          preview.mutate({ source_system: 'cablecast', base_url: url, username: username.trim() || null, password: password || null })
        }} className="rounded px-4 py-2">Preview import</button></div>
      </section>

      {plan && (
        <section className="grid gap-4 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)' }} aria-label="Import preview">
          <div>
            <h2 className="m-0 text-lg font-semibold">Review import plan</h2>
            <p className="text-sm">{shows.length} shows and {schedule.length} schedule entries proposed; {conflicts.length} conflicts and {skipped.length} skipped records. Preview has not changed station data.</p>
          </div>
          <div>
            <h3 className="text-base font-semibold">Shows to add</h3>
            {shows.length === 0 ? <p>None.</p> : <ul>{shows.map((show) => <li key={show.source_ref}>{show.title} <span className="text-sm">({show.source_ref})</span></li>)}</ul>}
          </div>
          <div>
            <h3 className="text-base font-semibold">Schedule entries to add</h3>
            {schedule.length === 0 ? <p>None.</p> : <ul>{schedule.map((item) => <li key={item.source_ref}>{item.channel_id}: {item.scheduled_at} — {item.show_source_ref}</li>)}</ul>}
          </div>
          <div>
            <h3 className="text-base font-semibold">Conflicts and skipped records</h3>
            {conflicts.length + skipped.length === 0 ? <p>None.</p> : <ul>
              {conflicts.map((item, index) => <li key={`conflict-${item.source_ref}-${index}`}>Conflict: {item.kind} {item.source_ref} — {item.reason}</li>)}
              {skipped.map((item, index) => <li key={`skip-${item.source_ref}-${index}`}>Skipped: {item.kind} {item.source_ref} — {item.reason}</li>)}
            </ul>}
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> I reviewed the proposed rows, conflicts, and skipped records.</label>
          <div><button type="button" disabled={busy || !reviewed || shows.length + schedule.length === 0} onClick={() => apply.mutate(plan)} className="rounded px-4 py-2">Apply this import</button></div>
        </section>
      )}

      {result && <ImportResult batch={result} />}

      <section className="grid gap-3 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)' }} aria-label="Import history">
        <h2 className="m-0 text-lg font-semibold">Import history</h2>
        {batches.isPending && <p role="status">Loading import history…</p>}
        {batches.isError && <p role="alert">Could not load import history. {message(batches.error)}</p>}
        {batches.data?.length === 0 && <p>No imports yet.</p>}
        <ul className="grid gap-3 p-0" style={{ listStyle: 'none' }}>
          {batches.data?.map((batch) => <li key={batch.import_batch_id} className="rounded border p-3" style={{ borderColor: 'var(--cc-line)' }}>
            <p className="m-0"><strong>{batch.import_batch_id}</strong> — {batch.status}; {batch.shows_created ?? 0} shows, {batch.schedule_items_created ?? 0} schedule entries</p>
            <p className="text-sm">Created {new Date(batch.created_at).toLocaleString()}</p>
            {batch.status === 'applied' && <>
              {rollbackId === batch.import_batch_id ? <div className="flex gap-2">
                <button type="button" disabled={busy} onClick={() => rollback.mutate(batch.import_batch_id)}>Confirm rollback</button>
                <button type="button" disabled={busy} onClick={() => setRollbackId(null)}>Cancel</button>
              </div> : <button type="button" disabled={busy} onClick={() => setRollbackId(batch.import_batch_id)}>Roll back this batch</button>}
            </>}
          </li>)}
        </ul>
      </section>
    </main>
  )
}
