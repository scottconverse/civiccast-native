import { staffApiRequest } from './client'
import type { ConnectionInfo, ImportBatch, ImportPlan } from '../types/api.generated'

export function previewStationImport(connection: ConnectionInfo): Promise<ImportPlan> {
  return staffApiRequest<ImportPlan>('/api/staff/migrate/dry-run', {
    method: 'POST',
    body: { connection },
  })
}

export function applyStationImport(plan: ImportPlan): Promise<ImportBatch> {
  return staffApiRequest<ImportBatch>('/api/staff/migrate/apply', {
    method: 'POST',
    body: { plan },
  })
}

export function listStationImportBatches(): Promise<ImportBatch[]> {
  return staffApiRequest<ImportBatch[]>('/api/staff/migrate/batches')
}

export function rollbackStationImport(importBatchId: string): Promise<ImportBatch> {
  return staffApiRequest<ImportBatch>('/api/staff/migrate/rollback', {
    method: 'POST',
    body: { import_batch_id: importBatchId },
  })
}
