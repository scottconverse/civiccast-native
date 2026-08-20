// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { agendaToChapters } from './agendaToChapters'
import type { PublicAgendaItem, PublicMeetingAgenda } from './types'

function item(overrides: Partial<PublicAgendaItem> & { item_id: string }): PublicAgendaItem {
  return {
    order: 0,
    number: null,
    title: 'Item',
    video_timecode_s: null,
    doc_anchor: null,
    ...overrides,
  }
}

function agenda(items: PublicAgendaItem[]): PublicMeetingAgenda {
  return {
    agenda_id: 'ag-1',
    meeting_asset_id: 'asset-1',
    source_doc_url: null,
    items,
  }
}

describe('agendaToChapters', () => {
  it('returns an empty list for a null agenda (caller falls back to asset chapters)', () => {
    expect(agendaToChapters(null)).toEqual([])
  })

  it('returns an empty list when no item has a video timecode', () => {
    const result = agendaToChapters(
      agenda([
        item({ item_id: 'a', title: 'Roll call', video_timecode_s: null }),
        item({ item_id: 'b', title: 'Adjourn', video_timecode_s: null }),
      ]),
    )
    expect(result).toEqual([])
  })

  it('drops items with a null timecode and keeps only the seekable ones, sorted ascending', () => {
    const result = agendaToChapters(
      agenda([
        item({ item_id: 'a', order: 0, title: 'Welcome', video_timecode_s: 60 }),
        item({ item_id: 'b', order: 1, title: 'Not synced yet', video_timecode_s: null }),
        item({ item_id: 'c', order: 2, title: 'Vote', video_timecode_s: 10 }),
      ]),
    )
    expect(result).toEqual([
      { t: 10, name: 'Vote' },
      { t: 60, name: 'Welcome' },
    ])
  })

  it('includes the item number in the chapter name when present', () => {
    const result = agendaToChapters(
      agenda([
        item({ item_id: 'a', number: '3.a', title: 'Approve minutes', video_timecode_s: 120 }),
        item({ item_id: 'b', number: null, title: 'Public comment', video_timecode_s: 240 }),
      ]),
    )
    expect(result).toEqual([
      { t: 120, name: '3.a Approve minutes' },
      { t: 240, name: 'Public comment' },
    ])
  })
})
