// UI-facing aliases over generated OpenAPI asset schemas.

import type {
  AssetMetadataUpdate as GeneratedAssetMetadataUpdate,
  Chapter as GeneratedChapter,
  StaffAssetRow,
} from './api.generated'

export type AssetState = StaffAssetRow['state']
export type RetentionPolicy = NonNullable<StaffAssetRow['retention_policy']>
export type Chapter = GeneratedChapter

export type AssetRow = StaffAssetRow & {
  description: string | null
  manifest_url: string | null
  file_path: string | null
  file_size_bytes: number | null
  duration_seconds: number | null
  codec_video: string | null
  codec_audio: string | null
  width_px: number | null
  height_px: number | null
  bitrate_bps: number | null
  format_name: string | null
  published_at: string | null
  trim_in_seconds: number | null
  trim_out_seconds: number | null
  chapters: Chapter[]
  retention_policy: RetentionPolicy
  retention_until: string | null
  version: number
  source_live_session_id: string | null
}

export type AssetMetadataUpdate = GeneratedAssetMetadataUpdate

export interface StateMeta {
  label: string
  tone: 'ok' | 'warn' | 'err' | 'info' | 'neutral'
  description: string
}

export const STATE_META: Record<AssetState, StateMeta> = {
  pending_ingest: {
    label: 'Analyzing',
    tone: 'info',
    description: 'ffprobe is running on the uploaded file.',
  },
  ingesting: {
    label: 'Ingesting',
    tone: 'info',
    description: 'File is being processed for ingest.',
  },
  validated: {
    label: 'Validated',
    tone: 'ok',
    description: 'Ingest passed. Ready for trim, scheduling, or publish.',
  },
  rejected: {
    label: 'Rejected',
    tone: 'err',
    description: 'File failed the validation gate. See details for the next step.',
  },
  recorded: {
    label: 'Recorded',
    tone: 'warn',
    description: 'Live recording is finalized and waiting for a publish workflow.',
  },
}
