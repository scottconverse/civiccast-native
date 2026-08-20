// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator card: the secondary audio programs (SAP / descriptive) configured for a
// channel (S11 gap 9 — secondary audio / SAP support). Read-only surface of the audio-track
// config; the GStreamer engine muxes each as an additional MPEG-TS PID (TV "SAP"
// button) and web/OTT exposes them as selectable audio renditions.

import { useQuery } from '@tanstack/react-query'

import { listAudioTracks } from '../api/client'
import type { AudioProgramTrack } from '../types/api.generated'

const KIND_LABEL: Record<string, string> = {
  primary: 'Primary',
  sap: 'SAP',
  descriptive: 'Descriptive',
}

export function AudioTracksView({
  tracks,
  error,
  loading = false,
}: {
  tracks: AudioProgramTrack[] | undefined
  error?: unknown
  loading?: boolean
}) {
  return (
    <section
      aria-label="Audio program tracks"
      className="space-y-2 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">Audio tracks (SAP / descriptive)</h2>
      {error ? (
        <div role="alert" style={{ color: 'var(--cc-err)' }}>
          Could not load audio tracks.
        </div>
      ) : loading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading audio tracks…
        </p>
      ) : !tracks || tracks.length === 0 ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Single audio program — no secondary (SAP / descriptive) tracks configured.
        </p>
      ) : (
        <ul className="space-y-1">
          {tracks.map((track) => (
            <li
              key={track.track_id}
              className="flex items-center justify-between gap-3 rounded-md p-2"
              style={{ background: 'var(--cc-paper)', border: '1px solid var(--cc-line)' }}
            >
              <span>
                <strong>{track.label}</strong>{' '}
                <span style={{ color: 'var(--cc-ink-3)' }}>
                  ({KIND_LABEL[track.kind] ?? track.kind} · {track.language})
                </span>
              </span>
              <span
                className="text-xs"
                style={{ color: track.enabled ? 'var(--cc-ok)' : 'var(--cc-ink-3)' }}
              >
                {track.enabled ? 'on air' : 'disabled'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function AudioTracksCard({ channelId }: { channelId: string }) {
  const query = useQuery({
    queryKey: ['audio-tracks', channelId],
    queryFn: () => listAudioTracks({ scope: 'channel', targetId: channelId }),
  })
  return (
    <AudioTracksView
      tracks={query.data}
      error={query.isError ? query.error : undefined}
      loading={query.isLoading}
    />
  )
}
