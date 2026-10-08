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
      'Schedule a recording, then publish it to residents separately before it appears on the portal.',
  },
  embargo: {
    label: 'Embargo',
    description:
      'Embargo release is unavailable in this build. Use Premiere, then publish the scheduled item to residents.',
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
