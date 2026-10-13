import { staffApiBlobRequest, staffApiRequest } from './client'

export interface StationBackupSchedule {
  enabled: boolean
  destination: string
  hour_utc: number
  minute_utc: number
  retention_count: number
  selected_media_roots: string[]
}

export interface StationBackupArtifact {
  backup_id: string
  file_name: string
  created_at: string
  size_bytes: number
}

export interface StationBackupStatus {
  schedule: StationBackupSchedule
  scheduled_passphrase_configured: boolean
  job: { phase: string; percent: number; updated_at?: string }
  last_success?: { backup_id: string; created_at: string; size_bytes: number } | null
  last_error?: string | null
  backups: StationBackupArtifact[]
}

export function getStationBackupStatus(): Promise<StationBackupStatus> {
  return staffApiRequest<StationBackupStatus>('/api/staff/backups/status')
}

export function createStationBackup(passphrase: string): Promise<StationBackupArtifact> {
  return staffApiRequest<StationBackupArtifact>('/api/staff/backups/create', {
    method: 'POST',
    body: { passphrase },
  })
}

export function updateStationBackupSchedule(
  schedule: StationBackupSchedule,
): Promise<StationBackupSchedule> {
  return staffApiRequest<StationBackupSchedule>('/api/staff/backups/schedule', {
    method: 'PUT',
    body: schedule,
  })
}

export function setScheduledBackupPassphrase(passphrase: string): Promise<{ configured: boolean }> {
  return staffApiRequest('/api/staff/backups/schedule/passphrase', {
    method: 'PUT',
    body: { passphrase },
  })
}

export function verifyStationBackup(
  backupId: string,
  passphrase: string,
): Promise<{ backup_id: string; valid: boolean; database_engine: string; files_verified: number }> {
  return staffApiRequest('/api/staff/backups/verify', {
    method: 'POST',
    body: { backup_id: backupId, passphrase },
  })
}

export function downloadStationBackup(backupId: string): Promise<Blob> {
  return staffApiBlobRequest(
    `/api/staff/backups/${encodeURIComponent(backupId)}/download`,
  )
}
