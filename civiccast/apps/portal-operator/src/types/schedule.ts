// UI-facing aliases over generated OpenAPI schedule schemas.
// Explicit unions stay here for the existing FE/BE drift test parser.

import type {
  ScheduleItemCreate as GeneratedScheduleItemCreate,
  ScheduleItemResponse,
} from './api.generated'

export type ScheduleMode = 'premiere' | 'embargo'

export type ScheduleState = 'scheduled' | 'cancelled' | 'published'

export type ScheduleItem = ScheduleItemResponse & {
  asset_title: string | null
  mode: ScheduleMode
  state: ScheduleState
}

export type ScheduleItemCreate = GeneratedScheduleItemCreate & {
  mode: ScheduleMode
  duration_seconds: number | null
}

export interface ScheduleConflictDetail {
  message: string
  conflicting_item: ScheduleItem
}

export interface ModeMeta {
  label: string
  description: string
}

export const MODE_META: Record<ScheduleMode, ModeMeta> = {
  premiere: {
    label: 'Premiere',
    description:
      'Publish a recorded asset to the public portal at a scheduled time.',
  },
  embargo: {
    label: 'Embargo',
    description:
      'Approve now; release becomes public at the embargo time.',
  },
}

export interface StateMeta {
  label: string
  tone: 'ok' | 'warn' | 'err' | 'info' | 'neutral'
}

export const SCHEDULE_STATE_META: Record<ScheduleState, StateMeta> = {
  scheduled: { label: 'Scheduled', tone: 'info' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  published: { label: 'Published', tone: 'ok' },
}
