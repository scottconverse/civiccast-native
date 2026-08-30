import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  ApiError,
  createSampleRehearsalUpload,
  createSetupLiveSource,
  getSourceSetup,
  uploadAssetFile,
} from '../../api/client'
import { manualLink } from '../../screens/manual-link'
import type {
  SourceSetupCreateRequest,
  SourceSetupOption,
  SourceSetupMutationResponse,
  SourceSetupSampleUploadResponse,
  UploadedAssetResponse,
} from '../../types/api.generated'

type WizardChoice = SourceSetupOption['id'] | 'local-upload'
type LiveChoice = SourceSetupCreateRequest['kind']

const LIVE_CHOICES = new Set<WizardChoice>(['usb-hdmi', 'phone-app', 'encoder', 'ndi'])

const CHOICE_COPY: Record<
  WizardChoice,
  {
    label: string
    summary: string
    endpointLabel?: string
    endpointHelp?: string
    endpointPlaceholder?: string
  }
> = {
  'usb-hdmi': {
    label: 'USB webcam or HDMI capture',
    summary: 'Use a capture app or encoder that sends a private RTMP feed to CivicCast.',
    endpointLabel: 'Private RTMP stream address',
    endpointHelp: 'Do not paste camera passwords here. Store credentials separately.',
    endpointPlaceholder: 'rtmp://127.0.0.1/live/council-room',
  },
  'phone-app': {
    label: 'Phone or tablet broadcast app',
    summary: 'Use a phone app on the same trusted network for a private preflight.',
    endpointLabel: 'Stream address from the app',
    endpointHelp: 'RTMP, RTMPS, or SRT addresses are accepted for this source.',
    endpointPlaceholder: 'rtmp://192.0.2.10/live/board-meeting',
  },
  encoder: {
    label: 'Hardware encoder or AV system',
    summary: 'Use an encoder from the meeting room or public-access control room.',
    endpointLabel: 'Encoder stream address',
    endpointHelp: 'RTMP, RTMPS, RTSP, RTSPS, or SRT addresses are accepted.',
    endpointPlaceholder: 'rtsp://encoder.example.local/live',
  },
  ndi: {
    label: 'NDI source',
    summary: 'Use a named NDI source already visible on the meeting network.',
    endpointLabel: 'NDI source name',
    endpointHelp: 'Enter the source name shown by the NDI tool, not a file path.',
    endpointPlaceholder: 'Council Room Camera',
  },
  'sample-upload': {
    label: 'Bundled sample video',
    summary: 'Let CivicCast create a short sample video for a private rehearsal.',
  },
  'local-upload': {
    label: 'Upload a short test video',
    summary: 'Use a local MP4, MOV, MKV, WebM, AVI, or MPEG-TS clip to rehearse without a camera.',
  },
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function sourceChoiceIsLive(choice: WizardChoice): choice is LiveChoice {
  return LIVE_CHOICES.has(choice)
}

function assetSlug(title: string): string {
  const base = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 42)
  const prefix = base.length >= 3 ? base : 'test-media'
  return `${prefix}-${Date.now().toString(36)}`.slice(0, 64)
}

function ResultPanel({
  source,
  sample,
  upload,
}: {
  source?: SourceSetupMutationResponse
  sample?: SourceSetupSampleUploadResponse
  upload?: UploadedAssetResponse
}) {
  const title = source?.live_source_id ?? sample?.asset_id ?? upload?.asset_id
  const message = source?.message ?? sample?.message ?? 'Upload accepted for rehearsal.'
  const nextStep =
    source?.next_step ??
    sample?.next_step ??
    'Run private rehearsal and confirm the resident preview.'
  if (!title) return null
  return (
    <div
      role="status"
      className="rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-ok-soft)', border: '1px solid var(--cc-ok)' }}
    >
      <div className="font-semibold">Ready: {title}</div>
      <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {message} <strong>Next step.</strong> {nextStep}
      </p>
    </div>
  )
}

export function SourceUploadWizard() {
  const queryClient = useQueryClient()
  const [choice, setChoice] = useState<WizardChoice>('sample-upload')
  const [label, setLabel] = useState('Council Room Camera')
  const [endpoint, setEndpoint] = useState('')
  const [uploadTitle, setUploadTitle] = useState('CivicCast test media')
  const [uploadDescription, setUploadDescription] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [lastSource, setLastSource] = useState<SourceSetupMutationResponse | undefined>()
  const [lastSample, setLastSample] = useState<SourceSetupSampleUploadResponse | undefined>()
  const [lastUpload, setLastUpload] = useState<UploadedAssetResponse | undefined>()

  const sourceReport = useQuery({
    queryKey: ['source-setup'],
    queryFn: getSourceSetup,
    retry: false,
  })

  const invalidateReadiness = () => {
    void queryClient.invalidateQueries({ queryKey: ['source-setup'] })
    void queryClient.invalidateQueries({ queryKey: ['live-sources'] })
    void queryClient.invalidateQueries({ queryKey: ['staff-assets'] })
    void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    void queryClient.invalidateQueries({ queryKey: ['safe-to-broadcast'] })
  }

  const liveSourceMutation = useMutation({
    mutationFn: () => {
      if (!sourceChoiceIsLive(choice)) throw new Error('Choose a camera/source type.')
      return createSetupLiveSource({
        kind: choice,
        label: label.trim(),
        endpoint: endpoint.trim(),
        channel_id: 'government',
      })
    },
    onSuccess: (response) => {
      setLastSource(response)
      setLastSample(undefined)
      setLastUpload(undefined)
      invalidateReadiness()
    },
  })

  const sampleMutation = useMutation({
    mutationFn: createSampleRehearsalUpload,
    onSuccess: (response) => {
      setLastSample(response)
      setLastSource(undefined)
      setLastUpload(undefined)
      invalidateReadiness()
    },
  })

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!uploadFile) throw new Error('Choose a short test video first.')
      return uploadAssetFile({
        assetId: assetSlug(uploadTitle),
        title: uploadTitle.trim(),
        description: uploadDescription.trim() || undefined,
        file: uploadFile,
        selectForRehearsal: true,
      })
    },
    onSuccess: (response) => {
      setLastUpload(response)
      setLastSource(undefined)
      setLastSample(undefined)
      invalidateReadiness()
    },
  })

  const current = CHOICE_COPY[choice]
  const busy = liveSourceMutation.isPending || sampleMutation.isPending || uploadMutation.isPending
  const error = liveSourceMutation.error ?? sampleMutation.error ?? uploadMutation.error
  const configured = sourceReport.data?.configured_source_count ?? 0

  return (
    <section
      className="grid gap-4 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">Camera or test media</h2>
          <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Choose the equipment in the room, or upload a short clip for a no-camera rehearsal.{' '}
            <Link to={manualLink('your-first-beta-workflow')} style={{ color: 'var(--cc-brand)' }}>
              Read the full walkthrough in the manual
            </Link>
            .
          </p>
        </div>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
          style={{
            background: configured > 0 ? 'var(--cc-ok-soft)' : 'var(--cc-warn-soft)',
            color: 'var(--cc-ink)',
          }}
        >
          {configured > 0 ? `${configured} source${configured === 1 ? '' : 's'}` : 'not set up yet'}
        </span>
      </div>

      <div className="grid gap-2 md:grid-cols-3">
        {(Object.keys(CHOICE_COPY) as WizardChoice[]).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setChoice(id)}
            className="rounded-md p-3 text-left text-sm"
            style={{
              background: choice === id ? 'var(--cc-info-soft)' : 'var(--cc-surface-2)',
              border: `1px solid ${choice === id ? 'var(--cc-info)' : 'var(--cc-line)'}`,
              color: 'var(--cc-ink)',
            }}
          >
            <span className="block font-semibold">{CHOICE_COPY[id].label}</span>
            <span className="mt-1 block text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              {CHOICE_COPY[id].summary}
            </span>
          </button>
        ))}
      </div>

      {sourceChoiceIsLive(choice) && (
        <form
          className="grid gap-3 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            liveSourceMutation.mutate()
          }}
        >
          <label className="grid gap-1 text-sm" htmlFor="source-label">
            <span className="font-semibold">Source name</span>
            <input
              id="source-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
          </label>
          <label className="grid gap-1 text-sm" htmlFor="source-endpoint">
            <span className="font-semibold">{current.endpointLabel}</span>
            <input
              id="source-endpoint"
              value={endpoint}
              placeholder={current.endpointPlaceholder}
              onChange={(event) => setEndpoint(event.target.value)}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
            <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              {current.endpointHelp}
            </span>
          </label>
          <button
            type="submit"
            disabled={busy || label.trim() === '' || endpoint.trim() === ''}
            className="w-fit rounded-md px-4 py-2 text-sm font-semibold md:col-span-2"
            style={{
              background: busy || label.trim() === '' || endpoint.trim() === '' ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: busy || label.trim() === '' || endpoint.trim() === '' ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            {liveSourceMutation.isPending ? 'Saving source...' : 'Save meeting source'}
          </button>
        </form>
      )}

      {choice === 'sample-upload' && (
        <div className="grid gap-2">
          <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            CivicCast will generate a two-second sample video, run ingest checks, and add it to Assets.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => sampleMutation.mutate()}
            className="w-fit rounded-md px-4 py-2 text-sm font-semibold"
            style={{ background: busy ? 'var(--cc-surface-3)' : 'var(--cc-brand)', color: busy ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)' }}
          >
            {sampleMutation.isPending ? 'Creating sample...' : 'Create sample media'}
          </button>
        </div>
      )}

      {choice === 'local-upload' && (
        <form
          className="grid gap-3 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            uploadMutation.mutate()
          }}
        >
          <label className="grid gap-1 text-sm" htmlFor="upload-title">
            <span className="font-semibold">Title</span>
            <input
              id="upload-title"
              value={uploadTitle}
              onChange={(event) => setUploadTitle(event.target.value)}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
          </label>
          <label className="grid gap-1 text-sm" htmlFor="upload-file">
            <span className="font-semibold">Video file</span>
            <input
              id="upload-file"
              type="file"
              accept="video/mp4,video/quicktime,video/webm,video/x-matroska,video/mp2t,video/x-msvideo"
              onChange={(event) => setUploadFile(event.currentTarget.files?.[0] ?? null)}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
          </label>
          <label className="grid gap-1 text-sm md:col-span-2" htmlFor="upload-description">
            <span className="font-semibold">Notes</span>
            <textarea
              id="upload-description"
              value={uploadDescription}
              onChange={(event) => setUploadDescription(event.target.value)}
              className="min-h-20 rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              placeholder="Optional notes for the test media."
            />
          </label>
          <button
            type="submit"
            disabled={busy || uploadTitle.trim() === '' || !uploadFile}
            className="w-fit rounded-md px-4 py-2 text-sm font-semibold md:col-span-2"
            style={{
              background: busy || uploadTitle.trim() === '' || !uploadFile ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: busy || uploadTitle.trim() === '' || !uploadFile ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            {uploadMutation.isPending ? 'Uploading...' : 'Upload test media'}
          </button>
        </form>
      )}

      {error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Source setup failed.')}
        </div>
      )}

      <ResultPanel source={lastSource} sample={lastSample} upload={lastUpload} />
    </section>
  )
}
