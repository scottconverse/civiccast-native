// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S7 / candidate #17 field evidence, findings 1-2: "the obvious 'add a
// video' screen has NO upload button and no file input at all" -- the only
// operator-side upload lived inside a First Setup rehearsal picker, one of
// six selectable cards, never labeled "Upload files." This is that missing
// control on the Assets/Library screen itself.
//
// Reuses the SAME `/api/staff/assets/upload` endpoint and form contract the
// First Setup "Upload a short test video" card already calls
// (`uploadAssetFileWithProgress` in api/client.ts, built on `uploadAssetFile`'s
// same FormData shape) -- never a second upload pipeline. The only
// difference is XHR instead of fetch, so this control can show real
// upload progress.

import { useId, useRef, useState } from 'react'
import { ApiError, uploadAssetFileWithProgress } from '../../api/client'
import type { UploadedAssetResponse } from '../../types/api.generated'

// Mirrors civiccast.schedule.ingest.SUPPORTED_FORMAT_TOKENS (the server's
// real, authoritative gate) -- this list is for fast client-side feedback
// only; the server validates for real and its rejection reason is what
// actually gets shown on a 422.
const ACCEPTED_EXTENSIONS = ['mp4', 'mov', 'mkv', 'webm', 'avi', 'ts', 'm2ts'] as const
const ACCEPTED_LABEL = 'MP4, MOV, MKV, WebM, AVI, or MPEG-TS'
const ACCEPT_ATTR =
  'video/mp4,video/quicktime,video/webm,video/x-matroska,video/mp2t,video/x-msvideo'

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot === -1 ? '' : filename.slice(dot + 1).toLowerCase()
}

function assetSlug(title: string): string {
  const base = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 42)
  const prefix = base.length >= 3 ? base : 'upload'
  return `${prefix}-${Date.now().toString(36)}`.slice(0, 64)
}

function titleFromFilename(filename: string): string {
  const withoutExt = filename.replace(/\.[^./\\]+$/, '')
  return withoutExt.replace(/[_-]+/g, ' ').trim() || 'Untitled recording'
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

type UploadStatus = 'idle' | 'ready' | 'uploading' | 'success' | 'error'

export interface AssetUploadControlProps {
  /** False only once role-check has resolved and the operator lacks upload rights. */
  canUpload: boolean
  /** Undefined while identity is still loading -- controls stay enabled-looking, not "denied." */
  roleCheckReady: boolean
  onUploaded: (asset: UploadedAssetResponse) => void
}

export function AssetUploadControl({ canUpload, roleCheckReady, onUploaded }: AssetUploadControlProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [typeError, setTypeError] = useState<string | null>(null)
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [lastUploaded, setLastUploaded] = useState<UploadedAssetResponse | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const fileInputId = useId()
  const titleInputId = useId()

  const disabled = roleCheckReady && !canUpload

  function reset() {
    setFile(null)
    setTitle('')
    setTypeError(null)
    setStatus('idle')
    setProgress(0)
    setErrorMessage(null)
    setLastUploaded(null)
  }

  function handleFileChange(selected: File | null) {
    setLastUploaded(null)
    setErrorMessage(null)
    if (!selected) {
      setFile(null)
      setTypeError(null)
      setStatus('idle')
      return
    }
    const ext = extensionOf(selected.name)
    if (!ACCEPTED_EXTENSIONS.includes(ext as (typeof ACCEPTED_EXTENSIONS)[number])) {
      setFile(null)
      setStatus('idle')
      setTypeError(
        `"${selected.name}" is not a supported video file. Accepted types: ${ACCEPTED_LABEL}.`,
      )
      return
    }
    setTypeError(null)
    setFile(selected)
    setTitle((current) => current || titleFromFilename(selected.name))
    setStatus('ready')
  }

  function startUpload() {
    if (!file || disabled) return
    const controller = new AbortController()
    abortRef.current = controller
    setStatus('uploading')
    setProgress(0)
    setErrorMessage(null)
    uploadAssetFileWithProgress(
      {
        assetId: assetSlug(title || file.name),
        title: title.trim() || titleFromFilename(file.name),
        file,
      },
      (percent) => setProgress(percent),
      controller.signal,
    )
      .then((response) => {
        setStatus('success')
        setLastUploaded(response)
        onUploaded(response)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          setStatus('ready')
          setProgress(0)
          return
        }
        setStatus('error')
        setErrorMessage(apiMessage(error, 'Upload failed.'))
      })
      .finally(() => {
        abortRef.current = null
      })
  }

  function cancelUpload() {
    abortRef.current?.abort()
  }

  if (!open) {
    return (
      <div className="px-6 pb-2">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-md px-3 py-1.5 text-xs font-semibold"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          Upload video
        </button>
      </div>
    )
  }

  return (
    <section
      aria-label="Upload video"
      className="mx-6 mb-4 flex flex-col gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="m-0 text-sm font-semibold">Upload video</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            Accepted types: {ACCEPTED_LABEL}. The file is added to this list once ingest
            validation finishes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            cancelUpload()
            setOpen(false)
            reset()
          }}
          className="rounded-md px-2 py-1 text-xs"
          style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
          aria-label="Close upload panel"
        >
          Close
        </button>
      </div>

      {disabled && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          A records clerk, meeting operator, or support administrator role is required to
          upload video.
        </p>
      )}

      {(status === 'idle' || status === 'ready' || status === 'error') && (
        <form
          className="grid gap-3 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            startUpload()
          }}
        >
          <label className="grid gap-1 text-sm" htmlFor={titleInputId}>
            <span className="font-semibold">Title</span>
            <input
              id={titleInputId}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              disabled={disabled}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              placeholder="e.g. City Council — August 12"
            />
          </label>
          <label className="grid gap-1 text-sm" htmlFor={fileInputId}>
            <span className="font-semibold">Video file</span>
            <input
              id={fileInputId}
              type="file"
              accept={ACCEPT_ATTR}
              disabled={disabled}
              onChange={(event) => handleFileChange(event.currentTarget.files?.[0] ?? null)}
              className="rounded-md px-3 py-2"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
            />
          </label>
          {typeError && (
            <div role="alert" className="text-xs md:col-span-2" style={{ color: 'var(--cc-err)' }}>
              {typeError}
            </div>
          )}
          {status === 'error' && errorMessage && (
            <div role="alert" className="text-xs md:col-span-2" style={{ color: 'var(--cc-err)' }}>
              <strong>Upload failed.</strong> {errorMessage}
            </div>
          )}
          <button
            type="submit"
            disabled={disabled || !file || title.trim() === ''}
            className="w-fit rounded-md px-4 py-2 text-sm font-semibold md:col-span-2"
            style={{
              background: disabled || !file || title.trim() === '' ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: disabled || !file || title.trim() === '' ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            {status === 'error' ? 'Try again' : 'Upload'}
          </button>
        </form>
      )}

      {status === 'uploading' && (
        <div className="grid gap-2">
          <div className="flex items-center justify-between text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            <span>Uploading {file?.name}…</span>
            <span className="cc-mono cc-tabular">{progress}%</span>
          </div>
          <progress value={progress} max={100} className="h-2 w-full" aria-label="Upload progress" />
          {/* aria-live status separate from the visual progress bar so screen
              readers get periodic announcements without the native
              <progress> element's own (browser-inconsistent) reporting. */}
          <p role="status" aria-live="polite" className="sr-only">
            Uploading {file?.name}, {progress} percent complete.
          </p>
          <button
            type="button"
            onClick={cancelUpload}
            className="w-fit rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
          >
            Cancel
          </button>
        </div>
      )}

      {status === 'success' && lastUploaded && (
        <div
          role="status"
          className="rounded-md p-3 text-sm"
          style={{ background: 'var(--cc-ok-soft)', border: '1px solid var(--cc-ok)' }}
        >
          <div className="font-semibold">Uploaded: {lastUploaded.title}</div>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            It now appears in the table below as <strong>{lastUploaded.state}</strong>. Ingest
            validation runs automatically; no further action is needed here.
          </p>
          <button
            type="button"
            onClick={reset}
            className="mt-2 w-fit rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
          >
            Upload another
          </button>
        </div>
      )}
    </section>
  )
}
