// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Candidate #17 field finding (reported TWICE): an asset that was
// ingest-Validated AND Packaged still showed a bare "Not ready" dot. The
// old Readiness column rendered the S7 lifecycle worker's proxy-transcode
// readiness verbatim, so whenever that worker had not run (fresh install,
// worker disabled, poll not yet due) EVERY asset -- packaged, published,
// whatever -- read "Not ready". That is the indicator lying about the
// asset the operator can see playing on the portal.
//
// The honest status of an asset is derivable from the asset row itself
// (state machine in civiccast/schedule/router.py: pending_ingest ->
// ingesting -> validated | rejected, plus recorded from live capture;
// packaging sets manifest_url via mark_packaged; publish sets
// published_at). The lifecycle worker's readiness row is a SECONDARY
// signal layered on top -- it can add "transcoding" / "missing file"
// detail, but its absence must never demote a packaged or published asset
// to "Not ready".

import type { ReadinessState } from '../ReadinessBadge'
import type { AssetRow } from '../../types/asset'

export type Tone = 'ok' | 'warn' | 'err' | 'info' | 'neutral'

export interface AssetReadinessRow {
  readiness_state: ReadinessState
  in_flight_jobs_count: number
  readiness_reason: string | null
}

export interface AssetStatus {
  /** Stable machine id, one per distinct lifecycle position. */
  id:
    | 'rejected'
    | 'missing_file'
    | 'validating'
    | 'ingesting'
    | 'published'
    | 'packaged'
    | 'transcoding'
    | 'queued_transcode'
    | 'not_packaged'
    | 'not_servable'
  label: string
  tone: Tone
  dot: string
  /** One-line plain explanation of what this status means / what happens next. */
  detail: string
}

export function deriveAssetStatus(
  row: AssetRow,
  readiness: AssetReadinessRow | undefined,
): AssetStatus {
  // Error states first -- they outrank everything, including published_at
  // (a published asset whose backing file went missing is a real incident).
  if (row.state === 'rejected') {
    return {
      id: 'rejected',
      label: 'Rejected',
      tone: 'err',
      dot: '🔴',
      detail:
        readiness?.readiness_reason ??
        'Ingest validation rejected this file. Open the asset for the rejection reason.',
    }
  }
  if (row.file_status === 'missing' || readiness?.readiness_state === 'missing_file') {
    return {
      id: 'missing_file',
      label: 'Missing file',
      tone: 'err',
      dot: '🔴',
      detail:
        readiness?.readiness_reason ??
        'Backing file not found on disk; relink or replace the source.',
    }
  }

  // In-progress ingest states.
  if (row.state === 'pending_ingest') {
    return {
      id: 'validating',
      label: 'Validating',
      tone: 'info',
      dot: '🔵',
      detail: 'Ingest validation is analyzing the file. This usually takes under a minute.',
    }
  }
  if (row.state === 'ingesting') {
    return {
      id: 'ingesting',
      label: 'Ingesting',
      tone: 'info',
      dot: '🔵',
      detail: 'The file is being processed for ingest.',
    }
  }

  // Success states -- what the asset row itself proves, regardless of
  // whether the lifecycle worker has run.
  if (row.published_at) {
    return {
      id: 'published',
      label: 'Published',
      tone: 'ok',
      dot: '🟢',
      detail: 'Live on the resident portal.',
    }
  }
  if (row.manifest_url) {
    return {
      id: 'packaged',
      label: 'Packaged',
      tone: 'ok',
      dot: '🟢',
      detail: 'Playable and ready to publish or schedule.',
    }
  }

  // Validated/recorded, not yet packaged. The lifecycle worker's transcode
  // pipeline may be mid-flight -- surface that when it is.
  if (readiness?.readiness_state === 'transcoding') {
    return {
      id: 'transcoding',
      label: 'Transcoding',
      tone: 'warn',
      dot: '🟡',
      detail:
        readiness.readiness_reason ??
        'A playback transcode is running; the asset stays usable meanwhile.',
    }
  }
  if (readiness?.readiness_state === 'pending_transcode') {
    return {
      id: 'queued_transcode',
      label: 'Queued for transcode',
      tone: 'warn',
      dot: '🟡',
      detail:
        readiness.readiness_reason ??
        'A playback transcode is queued; the asset stays usable meanwhile.',
    }
  }
  if (row.state === 'recorded') {
    return {
      id: 'not_servable',
      label: 'Not servable yet',
      tone: 'neutral',
      dot: '⚪',
      detail:
        'Live recording is finalized but has no public playback manifest yet, so residents cannot stream it.',
    }
  }
  return {
    id: 'not_packaged',
    label: 'Not packaged yet',
    tone: 'neutral',
    dot: '⚪',
    detail:
      'Validated and ready for trim or scheduling. Use "Package for playback" to make it streamable.',
  }
}
