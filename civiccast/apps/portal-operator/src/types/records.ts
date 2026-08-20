import type { RecordExportResponse } from './api.generated'

export const RECORD_STATUS_META: Record<
  RecordExportResponse['status'],
  { label: string; tone: 'ok' | 'err' }
> = {
  verified: { label: 'Verified', tone: 'ok' },
  failed: { label: 'Verification failed', tone: 'err' },
}

export type SignedRecordExport = RecordExportResponse
