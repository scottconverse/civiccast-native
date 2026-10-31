import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createStationBackup,
  downloadStationBackup,
  getStationBackupStatus,
  setScheduledBackupPassphrase,
  updateStationBackupSchedule,
  verifyStationBackup,
} from '../api/backups'

type ScheduleForm = {
  enabled: boolean
  destination: string
  timeUtc: string
  retentionCount: number
  mediaRootsText: string
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The backup operation could not be completed.'
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

export function BackupScreen() {
  const queryClient = useQueryClient()
  const statusQuery = useQuery({
    queryKey: ['station-backups'],
    queryFn: getStationBackupStatus,
    refetchInterval: 3000,
  })
  const [passphrase, setPassphrase] = useState('')
  const [confirmPassphrase, setConfirmPassphrase] = useState('')
  const [formOverride, setFormOverride] = useState<ScheduleForm | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [downloadPending, setDownloadPending] = useState(false)

  const persistedSchedule = statusQuery.data?.schedule
  const form = formOverride ?? (persistedSchedule ? {
    enabled: persistedSchedule.enabled,
    destination: persistedSchedule.destination,
    timeUtc: `${String(persistedSchedule.hour_utc).padStart(2, '0')}:${String(persistedSchedule.minute_utc).padStart(2, '0')}`,
    retentionCount: persistedSchedule.retention_count,
    mediaRootsText: persistedSchedule.selected_media_roots.join('\n'),
  } : {
    enabled: false,
    destination: '',
    timeUtc: '03:00',
    retentionCount: 14,
    mediaRootsText: '',
  })
  const setForm = (next: ScheduleForm) => setFormOverride(next)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['station-backups'] })
  const beginOperation = () => {
    setOperationError(null)
    setMessage(null)
  }
  const createMutation = useMutation({
    mutationFn: createStationBackup,
    onMutate: beginOperation,
    onSuccess: (backup) => {
      setMessage(`Encrypted backup created: ${backup.file_name}`)
      setPassphrase('')
      setConfirmPassphrase('')
      setOperationError(null)
      return refresh()
    },
    onError: (error) => setOperationError(errorMessage(error)),
  })
  const scheduleMutation = useMutation({
    mutationFn: updateStationBackupSchedule,
    onMutate: beginOperation,
    onSuccess: () => {
      setMessage('Daily backup schedule saved.')
      setOperationError(null)
      return refresh()
    },
    onError: (error) => setOperationError(errorMessage(error)),
  })
  const [scheduledPassphrase, setScheduledPassphrase] = useState('')
  const [confirmScheduledPassphrase, setConfirmScheduledPassphrase] = useState('')
  const scheduledPassphraseMutation = useMutation({
    mutationFn: setScheduledBackupPassphrase,
    onMutate: beginOperation,
    onSuccess: () => {
      setScheduledPassphrase('')
      setConfirmScheduledPassphrase('')
      setMessage('OS-protected recovery passphrase saved for unattended backups.')
      setOperationError(null)
      return refresh()
    },
    onError: (error) => setOperationError(errorMessage(error)),
  })
  const verifyMutation = useMutation({
    onMutate: beginOperation,
    mutationFn: ({ backupId, recoveryPassphrase }: { backupId: string; recoveryPassphrase: string }) =>
      verifyStationBackup(backupId, recoveryPassphrase),
    onSuccess: (result) => {
      setMessage(`Backup verified: ${result.files_verified} files authenticated.`)
      setOperationError(null)
    },
    onError: (error) => setOperationError(errorMessage(error)),
  })

  const status = statusQuery.data
  const backups = status?.backups ?? []
  const job = status?.job
  const passphrasesMatch = passphrase === confirmPassphrase
  const canCreate = passphrase.length >= 12 && passphrasesMatch && !createMutation.isPending
  const operationPending = createMutation.isPending || scheduleMutation.isPending
    || scheduledPassphraseMutation.isPending || verifyMutation.isPending || downloadPending

  return (
    <main className="mx-auto grid max-w-5xl gap-6 p-6" aria-labelledby="backup-title">
      <header>
        <p className="m-0 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--cc-ink-3)' }}>
          Station operations
        </p>
        <h1 id="backup-title" className="mb-1 mt-1 text-2xl font-semibold">Station backup and restore</h1>
        <p className="m-0 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Keep an encrypted copy of the station database, selected configuration and media. Store a copy away
          from this computer, and keep the recovery passphrase separately.
        </p>
      </header>

      {statusQuery.isPending && <p role="status">Loading backup status…</p>}
      {statusQuery.isError && (
        <p role="alert" className="rounded-md p-3" style={{ background: 'var(--cc-err-soft)' }}>
          Backup status could not be loaded. {errorMessage(statusQuery.error)}
        </p>
      )}
      {!operationPending && (operationError || status?.last_error) && (
        <p role="alert" className="rounded-md p-3" style={{ background: 'var(--cc-err-soft)' }}>
          {operationError ?? status?.last_error}
        </p>
      )}
      {message && <p role="status" className="rounded-md p-3" style={{ background: 'var(--cc-ok-soft)' }}>{message}</p>}

      <section className="grid gap-3 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)' }}>
        <div>
          <h2 className="m-0 text-lg font-semibold">Create an encrypted backup</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Use at least 12 characters. CivicCast uses this passphrase to encrypt the portable archive and does not save it.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-sm font-medium">
            Recovery passphrase
            <input type="password" autoComplete="new-password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Confirm passphrase
            <input type="password" autoComplete="new-password" value={confirmPassphrase} onChange={(event) => setConfirmPassphrase(event.target.value)} />
          </label>
        </div>
        {confirmPassphrase && !passphrasesMatch && <p className="m-0 text-sm" role="alert">The passphrases do not match.</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" disabled={!canCreate} onClick={() => createMutation.mutate(passphrase)}>
            {createMutation.isPending ? 'Creating encrypted backup…' : 'Create backup'}
          </button>
          {job && job.phase !== 'idle' && !(operationPending && job.phase === 'failed') && (
            <div className="min-w-52 flex-1" aria-live="polite">
              <div className="mb-1 flex justify-between text-xs"><span>{job.phase.replaceAll('-', ' ')}</span><span>{job.percent}%</span></div>
              <progress className="w-full" max={100} value={job.percent} aria-label="Backup progress" />
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-3 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)' }}>
        <div>
          <h2 className="m-0 text-lg font-semibold">Daily schedule</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            The station service runs this schedule in UTC. Set a recovery passphrase below before enabling unattended encryption.
          </p>
        </div>
        <div className="grid gap-2 rounded-md border p-3" style={{ borderColor: 'var(--cc-line)' }}>
          <p className="m-0 text-sm" role="status">
            Unattended recovery passphrase: {status?.scheduled_passphrase_configured ? 'configured in protected station storage' : 'not configured'}.
          </p>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            This passphrase is stored by the station's protected secret provider and is not included in the backup archive. Keep it available to the operator restoring the station.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium">
              Unattended recovery passphrase
              <input type="password" autoComplete="new-password" value={scheduledPassphrase} onChange={(event) => setScheduledPassphrase(event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Confirm unattended passphrase
              <input type="password" autoComplete="new-password" value={confirmScheduledPassphrase} onChange={(event) => setConfirmScheduledPassphrase(event.target.value)} />
            </label>
          </div>
          {confirmScheduledPassphrase && scheduledPassphrase !== confirmScheduledPassphrase && <p className="m-0 text-sm" role="alert">The unattended passphrases do not match.</p>}
          <div><button type="button" disabled={scheduledPassphrase.length < 12 || scheduledPassphrase !== confirmScheduledPassphrase || scheduledPassphraseMutation.isPending} onClick={() => scheduledPassphraseMutation.mutate(scheduledPassphrase)}>
            {scheduledPassphraseMutation.isPending ? 'Saving protected passphrase…' : 'Save unattended passphrase'}
          </button></div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.enabled} disabled={!status?.scheduled_passphrase_configured} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
          Enable daily backup
        </label>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="grid gap-1 text-sm font-medium md:col-span-2">
            Destination folder
            <input type="text" value={form.destination} onChange={(event) => setForm({ ...form, destination: event.target.value })} placeholder="Choose a local or attached backup drive" />
          </label>
          <label className="grid gap-1 text-sm font-medium">
            UTC time
            <input type="time" value={form.timeUtc} onChange={(event) => setForm({ ...form, timeUtc: event.target.value })} />
          </label>
        </div>
        <label className="grid max-w-xs gap-1 text-sm font-medium">
          Keep recent backups
          <input type="number" min={1} max={100} value={form.retentionCount} onChange={(event) => setForm({ ...form, retentionCount: Number(event.target.value) })} />
        </label>
        <label className="grid gap-1 text-sm font-medium">
          Selected media folders (one absolute path per line)
          <textarea rows={4} value={form.mediaRootsText} onChange={(event) => setForm({ ...form, mediaRootsText: event.target.value })} placeholder={'C:\\CivicCast\\media\\recordings\nD:\\StationMedia'} />
          <span className="text-xs font-normal" style={{ color: 'var(--cc-ink-2)' }}>
            Every file under these folders is included. Choose only roots with media you want in the encrypted station backup.
          </span>
        </label>
        <div><button type="button" disabled={scheduleMutation.isPending || !form.destination.trim()} onClick={() => {
          const [hour, minute] = form.timeUtc.split(':').map(Number)
          scheduleMutation.mutate({
            enabled: form.enabled,
            destination: form.destination.trim(),
            hour_utc: hour,
            minute_utc: minute,
            retention_count: form.retentionCount,
            selected_media_roots: form.mediaRootsText.split(/\r?\n/).map((root) => root.trim()).filter(Boolean),
          })
        }}>{scheduleMutation.isPending ? 'Saving…' : 'Save schedule'}</button></div>
      </section>

      <section className="grid gap-3 rounded-lg border p-4" style={{ borderColor: 'var(--cc-line)', background: 'var(--cc-surface)' }}>
        <div>
          <h2 className="m-0 text-lg font-semibold">Available backups</h2>
          <p className="mb-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Verify a file before relying on it. Download a copy to storage on a different device.
          </p>
        </div>
        {backups.length === 0 ? (
          <p className="m-0 rounded-md p-3 text-sm" style={{ background: 'var(--cc-info-soft)' }}>No station backups are available yet. Create one now or enable a daily schedule.</p>
        ) : (
          <ul className="m-0 grid list-none gap-2 p-0">
            {backups.map((backup) => (
              <li key={backup.backup_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3" style={{ borderColor: 'var(--cc-line)' }}>
                <div>
                  <p className="m-0 font-medium">{backup.file_name}</p>
                  <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>{new Date(backup.created_at).toLocaleString()} · {(backup.size_bytes / (1024 * 1024)).toFixed(1)} MB</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={passphrase.length < 12 || verifyMutation.isPending} onClick={() => verifyMutation.mutate({ backupId: backup.backup_id, recoveryPassphrase: passphrase })}>Verify</button>
                  <button type="button" disabled={downloadPending} onClick={async () => {
                    beginOperation()
                    setDownloadPending(true)
                    try {
                      downloadBlob(await downloadStationBackup(backup.backup_id), backup.file_name)
                      setOperationError(null)
                    } catch (error) {
                      setOperationError(errorMessage(error))
                    } finally {
                      setDownloadPending(false)
                    }
                  }}>Download</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <aside className="rounded-lg p-4 text-sm" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
        <h2 className="m-0 text-base font-semibold">Replacing a station computer?</h2>
        <p className="mb-0 mt-1">
          Restore on the replacement computer with CivicCast stopped. The offline <code>civiccast backup restore</code> workflow requires an explicit target database, mapped file destinations and acknowledgement that this computer’s station credentials and service settings will also be replaced. Review the destination preview before confirming. PostgreSQL may be newly provisioned or already contain replacement-station objects; preserve existing data first. This is a full station restore, not an isolated database clone. See the Station Backup and Restore operator guide.
        </p>
      </aside>
    </main>
  )
}
