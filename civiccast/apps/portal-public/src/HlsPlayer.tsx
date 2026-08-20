import { useEffect, useRef, useState, type RefObject } from 'react'
import type Hls from 'hls.js'
import { emitAnalyticsEvent, type AnalyticsContext } from './analytics'

type PlayerState = 'idle' | 'loading' | 'ready' | 'error'

const HEARTBEAT_SECONDS = 60

/**
 * Imperative handle exposed to a parent that needs to drive the player
 * (S25 §6: agenda items seek the video to their timecode). The parent
 * passes in a ref; the player publishes a `seekTo` function on mount and
 * keeps it pointing at the live <video> element across manifest changes.
 */
export interface HlsPlayerHandle {
  seekTo: (seconds: number) => void
}

interface HlsPlayerProps {
  manifestUrl: string
  posterUrl?: string
  /** Privacy-safe playback analytics context (Stage G); omit to disable. */
  analytics?: AnalyticsContext
  /** Optional imperative handle for external seek (S25 agenda integration). */
  handleRef?: RefObject<HlsPlayerHandle | null>
}

interface SubtitleTrackOption {
  id: number
  label: string
  language: string
}

function selectNativeTextTrack(nativeTracks: TextTrackList, trackId: number) {
  for (let index = 0; index < nativeTracks.length; index += 1) {
    nativeTracks[index].mode = index === trackId ? 'showing' : 'disabled'
  }
}

/**
 * HLS.js-backed VOD player.
 *
 * Native HLS (Safari, iOS) bypasses hls.js and uses the <video> element directly.
 * Other browsers dynamically import hls.js on mount for adaptive bitrate
 * switching across the 5-variant ladder (4 content renditions + slate
 * fallback). The dynamic import keeps the initial bundle small — first
 * paint of the portal page does not pay the hls.js download cost.
 */
export function HlsPlayer({
  manifestUrl,
  posterUrl,
  analytics,
  handleRef,
}: HlsPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef = useRef<Hls | null>(null)
  const [state, setState] = useState<PlayerState>('idle')

  // Publish/withdraw the imperative seek handle for the agenda sidebar
  // (S25 §6). Clamp to [0, duration] when known, so a stale agenda timecode
  // beyond the video end falls onto the last frame instead of throwing.
  useEffect(() => {
    if (!handleRef) return
    handleRef.current = {
      seekTo: (seconds: number) => {
        const video = videoRef.current
        if (!video) return
        const duration = Number.isFinite(video.duration) ? video.duration : null
        const target = duration !== null ? Math.min(Math.max(0, seconds), duration) : Math.max(0, seconds)
        video.currentTime = target
        if (video.paused) {
          void video.play().catch(() => {
            // Autoplay can be blocked; the seek still landed, leave UI as-is.
          })
        }
      },
    }
    return () => {
      handleRef.current = null
    }
  }, [handleRef])
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [subtitleTracks, setSubtitleTracks] = useState<SubtitleTrackOption[]>([])
  const [selectedSubtitleTrack, setSelectedSubtitleTrack] = useState<number>(-1)
  const analyticsRef = useRef<AnalyticsContext | undefined>(analytics)
  useEffect(() => {
    analyticsRef.current = analytics
  }, [analytics])

  // Playback analytics (audit sprint Stage G): start once per source, a
  // coarse heartbeat while playing, complete on ended, error on failure.
  // Fail-silent and identifier-free; see src/analytics.ts.
  useEffect(() => {
    const video = videoRef.current
    const context = analyticsRef.current
    if (!video || !context) return

    let started = false
    let heartbeat: number | undefined
    const emit = (
      name: 'playback_start' | 'playback_heartbeat' | 'playback_complete',
      properties: Record<string, string | number | boolean> = {},
    ) => {
      emitAnalyticsEvent(name, { ...analyticsRef.current, properties })
    }
    const onPlay = () => {
      if (!started) {
        started = true
        emit('playback_start')
      }
      if (heartbeat === undefined) {
        heartbeat = window.setInterval(() => {
          if (!video.paused && !video.ended) {
            emit('playback_heartbeat', {
              position_seconds: Math.floor(video.currentTime),
            })
          }
        }, HEARTBEAT_SECONDS * 1000)
      }
    }
    const onEnded = () => {
      emit('playback_complete', { position_seconds: Math.floor(video.currentTime) })
    }
    video.addEventListener('play', onPlay)
    video.addEventListener('ended', onEnded)
    return () => {
      video.removeEventListener('play', onPlay)
      video.removeEventListener('ended', onEnded)
      if (heartbeat !== undefined) window.clearInterval(heartbeat)
    }
  }, [manifestUrl])

  const errorEmittedRef = useRef(false)
  useEffect(() => {
    errorEmittedRef.current = false
  }, [manifestUrl])
  useEffect(() => {
    if (state === 'error' && analyticsRef.current && !errorEmittedRef.current) {
      errorEmittedRef.current = true
      // Generic reason only — never URLs or error internals (privacy posture).
      emitAnalyticsEvent('playback_error', {
        ...analyticsRef.current,
        properties: { reason: 'playback_failed' },
      })
    }
  }, [state])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    setState('loading')
    setErrorMessage('')
    setSubtitleTracks([])
    setSelectedSubtitleTrack(-1)
    hlsRef.current = null

    // Prefer hls.js when it is supported so Chromium/Firefox can parse HLS
    // subtitle tracks. Safari/iOS fall back to the native HLS path below.
    let hls: Hls | null = null
    let cancelled = false
    let cleanupNativeHls: (() => void) | null = null

    void import('hls.js').then((mod) => {
      if (cancelled) return
      const HlsCtor = mod.default
      if (!HlsCtor.isSupported()) {
        if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = manifestUrl
          const nativeTracks = video.textTracks
          const syncNativeSubtitleTracks = () => {
            const tracks = Array.from(nativeTracks)
            setSubtitleTracks(
              tracks.map((track, index) => ({
                id: index,
                label: track.label || track.language || `Track ${index + 1}`,
                language: track.language || '',
              })),
            )
            setSelectedSubtitleTrack(
              tracks.findIndex((track) => track.mode === 'showing'),
            )
          }
          const onCanPlay = () => setState('ready')
          const onError = () => {
            setState('error')
            setErrorMessage('The video could not be loaded. Please try again.')
          }
          syncNativeSubtitleTracks()
          video.addEventListener('loadedmetadata', syncNativeSubtitleTracks)
          video.addEventListener('canplay', onCanPlay)
          video.addEventListener('error', onError)
          nativeTracks.addEventListener('addtrack', syncNativeSubtitleTracks)
          nativeTracks.addEventListener('removetrack', syncNativeSubtitleTracks)
          nativeTracks.addEventListener('change', syncNativeSubtitleTracks)
          cleanupNativeHls = () => {
            video.removeEventListener('loadedmetadata', syncNativeSubtitleTracks)
            video.removeEventListener('canplay', onCanPlay)
            video.removeEventListener('error', onError)
            nativeTracks.removeEventListener('addtrack', syncNativeSubtitleTracks)
            nativeTracks.removeEventListener('removetrack', syncNativeSubtitleTracks)
            nativeTracks.removeEventListener('change', syncNativeSubtitleTracks)
          }
          return
        }
        setState('error')
        setErrorMessage(
          'Your browser does not support HLS playback. Please try a recent version of Chrome, Firefox, Safari, or Edge.',
        )
        return
      }

      hls = new HlsCtor({ enableWorker: true, lowLatencyMode: false })
      hlsRef.current = hls
      const syncSubtitleTracks = () => {
        const tracks = hls?.subtitleTracks ?? []
        if (tracks.length === 0) return
        setSubtitleTracks(
          tracks.map((track, index) => ({
            id: index,
            label: track.name || track.lang || `Track ${index + 1}`,
            language: track.lang || '',
          })),
        )
        setSelectedSubtitleTrack(hls?.subtitleTrack ?? -1)
      }
      hls.attachMedia(video)
      hls.on(HlsCtor.Events.MEDIA_ATTACHED, () => {
        hls?.loadSource(manifestUrl)
      })
      hls.on(HlsCtor.Events.MANIFEST_PARSED, () => {
        syncSubtitleTracks()
        setState('ready')
      })
      hls.on(HlsCtor.Events.SUBTITLE_TRACKS_UPDATED, () => {
        syncSubtitleTracks()
      })
      hls.on(HlsCtor.Events.SUBTITLE_TRACK_SWITCH, (_event, data) => {
        setSelectedSubtitleTrack(data.id)
      })
      hls.on(HlsCtor.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          setState('error')
          setErrorMessage(
            data.type === HlsCtor.ErrorTypes.NETWORK_ERROR
              ? 'Network error while loading the video. Check your connection and try again.'
              : 'The video could not be played. The stream may be unavailable.',
          )
        }
      })
    })

    return () => {
      cancelled = true
      cleanupNativeHls?.()
      hls?.destroy()
      if (hlsRef.current === hls) hlsRef.current = null
    }
  }, [manifestUrl])

  const selectSubtitleTrack = (trackId: number) => {
    const hls = hlsRef.current
    if (hls) {
      hls.subtitleTrack = trackId
      hls.subtitleDisplay = trackId >= 0
      setSelectedSubtitleTrack(trackId)
      return
    }

    const nativeTracks = videoRef.current?.textTracks
    if (!nativeTracks) return
    selectNativeTextTrack(nativeTracks, trackId)
    setSelectedSubtitleTrack(trackId)
  }

  return (
    <div className="overflow-hidden rounded-lg bg-black shadow-lg ring-1 ring-white/10">
      <div className="relative w-full">
        <div className="aspect-video w-full">
          <video
            ref={videoRef}
            controls
            playsInline
            poster={posterUrl}
            aria-label="Meeting video player"
            className="h-full w-full"
          />
        </div>

        {state === 'loading' && (
          <div
            role="status"
            aria-live="polite"
            className="absolute inset-0 flex items-center justify-center bg-black/40 text-civiccast-mist"
          >
            <span className="rounded-md bg-black/70 px-4 py-2 text-sm font-medium">
              Loading video&hellip;
            </span>
          </div>
        )}

        {state === 'error' && (
          <div
            role="alert"
            className="absolute inset-0 flex items-center justify-center bg-black/70 p-4 text-center"
          >
            <div className="max-w-md rounded-md border border-red-500/40 bg-red-950/40 p-4 text-sm text-red-100">
              {errorMessage}
            </div>
          </div>
        )}
      </div>

      {subtitleTracks.length > 0 && (
        <fieldset className="border-t border-white/10 bg-[#0f1712] px-4 py-3">
          <legend className="sr-only">Caption track controls</legend>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="mr-1 text-xs font-semibold uppercase tracking-[0.14em] text-stone-300">
              Captions
            </span>
            <CaptionButton
              label="Off"
              active={selectedSubtitleTrack < 0}
              onClick={() => selectSubtitleTrack(-1)}
            />
            {subtitleTracks.map((track) => (
              <CaptionButton
                key={`${track.language}-${track.id}`}
                label={track.label}
                active={selectedSubtitleTrack === track.id}
                onClick={() => selectSubtitleTrack(track.id)}
              />
            ))}
          </div>
        </fieldset>
      )}
    </div>
  )
}

function CaptionButton({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="rounded-md border px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-200"
      style={{
        background: active ? 'rgb(209 250 229)' : 'rgb(31 41 55)',
        borderColor: active ? 'rgb(167 243 208)' : 'rgb(75 85 99)',
        color: active ? 'rgb(6 78 59)' : 'rgb(243 244 246)',
      }}
    >
      {label}
    </button>
  )
}
