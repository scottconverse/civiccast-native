import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getStaffAssetPlaybackGrant } from '../../api/client'
import type { TranscriptRange } from '../../types/api.generated'

function fmtTime(seconds: number): string {
  const whole = Math.floor(seconds)
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TranscriptCuePlayer({
  assetId,
  ranges,
  activeRange,
}: {
  assetId: string
  ranges: TranscriptRange[]
  activeRange: TranscriptRange | null
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [mediaReady, setMediaReady] = useState(false)
  const [playbackError, setPlaybackError] = useState<string | null>(null)
  const [seekMessage, setSeekMessage] = useState<string | null>(null)
  const [previewAttempt, setPreviewAttempt] = useState(0)
  const playbackQuery = useQuery({
    queryKey: ['staff-asset-playback-grant', assetId],
    queryFn: () => getStaffAssetPlaybackGrant(assetId),
    enabled: activeRange !== null,
    retry: false,
    staleTime: 8 * 60 * 1000,
  })
  const grant = playbackQuery.data
  const packagedPlayback = grant?.playback_kind === 'hls' && Boolean(grant.packaged_url)
  const mediaUrl = grant
    ? packagedPlayback
      ? grant.packaged_url
      : grant.url
    : null
  const hasSelection = activeRange !== null

  const renewPlayback = async () => {
    setPlaybackError(null)
    setMediaReady(false)
    setSeekMessage(null)
    await playbackQuery.refetch()
    setPreviewAttempt((attempt) => attempt + 1)
  }

  useEffect(() => {
    const video = videoRef.current
    if (!video || !hasSelection || !grant || !mediaUrl) return

    let cancelled = false
    let destroyHls: (() => void) | null = null
    setMediaReady(false)
    setPlaybackError(null)
    setSeekMessage(null)

    const onLoadedMetadata = () => {
      if (!cancelled) setMediaReady(true)
    }
    const onNativeError = () => {
      if (!cancelled) {
        setPlaybackError(
          packagedPlayback
            ? 'The packaged source preview could not be played. Repackage the recording, then retry the citation.'
            : 'This source format could not be played in this browser. Package the recording for HLS playback, then retry the citation.',
        )
      }
    }
    video.addEventListener('loadedmetadata', onLoadedMetadata)
    video.addEventListener('error', onNativeError)

    const attachNativeSource = () => {
      if (!grant.source_content_type || !video.canPlayType(grant.source_content_type)) {
        setPlaybackError(
          'This source format cannot play natively in this browser. Package the recording for HLS playback, then retry the citation.',
        )
        return
      }
      video.src = mediaUrl
    }

    if (packagedPlayback) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = mediaUrl
      } else {
        void import('hls.js')
          .then(({ default: HlsConstructor }) => {
            if (cancelled) return
            if (!HlsConstructor.isSupported()) {
              setPlaybackError('This browser does not support packaged HLS playback.')
              return
            }
            const hls = new HlsConstructor({ enableWorker: true, lowLatencyMode: false })
            destroyHls = () => hls.destroy()
            hls.on(HlsConstructor.Events.MANIFEST_PARSED, () => {
              if (!cancelled && video.readyState >= 1) setMediaReady(true)
            })
            hls.on(HlsConstructor.Events.ERROR, (_event, data) => {
              if (!cancelled && data.fatal) {
                setPlaybackError(
                  'The packaged source preview could not be played. Repackage the recording, then retry the citation.',
                )
              }
            })
            hls.attachMedia(video)
            hls.loadSource(mediaUrl)
          })
          .catch(() => {
            if (!cancelled) setPlaybackError('The HLS playback component could not be loaded. Refresh and retry.')
          })
      }
    } else {
      attachNativeSource()
    }

    return () => {
      cancelled = true
      video.removeEventListener('loadedmetadata', onLoadedMetadata)
      video.removeEventListener('error', onNativeError)
      destroyHls?.()
      video.removeAttribute('src')
      video.load()
    }
  }, [hasSelection, grant, mediaUrl, packagedPlayback, previewAttempt])

  useEffect(() => {
    const video = videoRef.current
    const citation = activeRange
    if (!video || !citation || !grant || !mediaReady) return
    const sourceOffset = packagedPlayback ? grant.source_offset_seconds : 0
    const seekToCitation = () => {
      const target = citation.start_seconds - sourceOffset
      if (target < 0) {
        setSeekMessage(
          `This citation starts at ${fmtTime(citation.start_seconds)}, before the packaged preview begins at ${fmtTime(sourceOffset)}. Repackage the recording with a wider range to play this passage.`,
        )
        return
      }
      if (Number.isFinite(video.duration) && target >= video.duration) {
        setSeekMessage(
          'This citation falls outside the packaged preview. Repackage the recording with a wider range to play this passage.',
        )
        return
      }
      video.currentTime = target
      const citationEnd = citation.end_seconds - sourceOffset
      if (Number.isFinite(video.duration) && citationEnd > video.duration + 0.1) {
        setSeekMessage(
          `Source positioned at ${fmtTime(citation.start_seconds)}, but this packaged preview ends before the citation at ${fmtTime(citation.end_seconds)}. Repackage the recording with a wider range to play the full passage.`,
        )
      } else {
        setSeekMessage(
          `Source positioned at ${fmtTime(citation.start_seconds)}. Press Play to hear or view this cited passage.`,
        )
      }
    }
    if (video.readyState >= 1) {
      seekToCitation()
      return
    }
    video.addEventListener('loadedmetadata', seekToCitation, { once: true })
    return () => video.removeEventListener('loadedmetadata', seekToCitation)
  }, [
    activeRange,
    grant,
    mediaReady,
    packagedPlayback,
  ])

  return (
    <section
      aria-label="Inline transcript player"
      className="grid content-start gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          Source recording
        </div>
        <div className="mt-1 text-sm font-semibold">
          {activeRange
            ? `${activeRange.cue_id} / ${fmtTime(activeRange.start_seconds)}-${fmtTime(activeRange.end_seconds)}`
            : 'Select a cited timestamp to seek the source'}
        </div>
      </div>

      {!activeRange && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Choose a timestamp beside a sourced claim to load the authorized source preview.
        </p>
      )}
      {activeRange && playbackQuery.isLoading && (
        <div role="status" className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Preparing private source playback…
        </div>
      )}
      {activeRange && playbackQuery.isError && (
        <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
          Source playback is unavailable. Confirm staff access and that the source recording is on the station.
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => void playbackQuery.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      {activeRange && grant && mediaUrl && (
        <video
          ref={videoRef}
          aria-label="Summary source recording"
          className="w-full rounded-md"
          controls
          preload="metadata"
          style={{ background: '#111', aspectRatio: '16 / 9', display: playbackError ? 'none' : undefined }}
        />
      )}
      {activeRange && playbackError && (
        <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
          {playbackError}
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => void renewPlayback()}
          >
            Renew playback
          </button>
        </div>
      )}
      {activeRange && seekMessage && (
        <div role="status" className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          {seekMessage}
        </div>
      )}

      {ranges.length > 0 && (
        <div className="grid gap-2" role="list" aria-label="Transcript cue ranges">
          {ranges.map((range) => {
            const selected =
              range.cue_id === activeRange?.cue_id && range.start_seconds === activeRange.start_seconds
            return (
              <div
                key={`${range.cue_id}-${range.start_seconds}`}
                role="listitem"
                aria-current={selected ? 'true' : undefined}
                className="rounded-md px-3 py-2 text-xs"
                style={{
                  background: selected ? 'var(--cc-brand-soft)' : 'var(--cc-surface-2)',
                  border: selected ? '1px solid var(--cc-brand)' : '1px solid var(--cc-line)',
                  color: selected ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
                }}
              >
                {range.cue_id}: {fmtTime(range.start_seconds)}-{fmtTime(range.end_seconds)}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
