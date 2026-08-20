// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// S25 §6 — single source of truth for meeting chapters.
//
// When an agenda exists for a meeting asset, the meeting's chapter list MUST
// derive from its published agenda items (no divergent chapter list). This
// helper performs that projection — call it at the player chapter-consumer
// site and fall back to the asset's own chapter list only when this returns
// an empty result (i.e. no agenda or no items with a timecode).
//
// Integration site (TODO when the public-portal player grows a chapter UI):
//   const chapters = agendaToChapters(agenda) || asset.chapters_json
// Today HlsPlayer.tsx does not consume a chapter list; the integration is
// staged in MeetingAgendaSidebar (clicking an item seeks the <video> via the
// onSeek callback the screen passes in).

import type { PublicMeetingAgenda } from './types'

export interface Chapter {
  /** Offset into the meeting video, in seconds. */
  t: number
  /** Display label (number + title, or just title). */
  name: string
}

/**
 * Project a published agenda into the meeting's canonical chapter list.
 *
 * - Returns an empty array when the agenda is null or has no items with a
 *   non-null `video_timecode_s` (so callers can `chapters.length === 0 ?`
 *   fall back to the asset's own chapter list).
 * - Drops items whose `video_timecode_s` is null — they can't be seek targets.
 * - Sorts ascending by timecode so the chapter list is monotonic regardless
 *   of agenda item `order` (an operator who reorders items without resetting
 *   timecodes still gets a coherent chapter strip).
 * - Each chapter `name` includes the item `number` when present
 *   (e.g. "3.a Approve minutes") and falls back to just the title.
 */
export function agendaToChapters(agenda: PublicMeetingAgenda | null): Chapter[] {
  if (!agenda) return []
  const chapters: Chapter[] = []
  for (const item of agenda.items) {
    if (item.video_timecode_s === null) continue
    const name = item.number ? `${item.number} ${item.title}` : item.title
    chapters.push({ t: item.video_timecode_s, name })
  }
  chapters.sort((a, b) => a.t - b.t)
  return chapters
}
