// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  uploadAssetFileWithProgress: vi.fn(),
}))

import { ApiError, uploadAssetFileWithProgress } from '../../api/client'
import type { UploadedAssetResponse } from '../../types/api.generated'
import { AssetUploadControl } from './AssetUploadControl'

afterEach(cleanup)

function mp4(name = 'council-meeting.mp4'): File {
  return new File(['video-bytes'], name, { type: 'video/mp4' })
}

function renderControl(overrides: Partial<Parameters<typeof AssetUploadControl>[0]> = {}) {
  const onUploaded = vi.fn()
  return {
    ...render(
      <AssetUploadControl canUpload roleCheckReady onUploaded={onUploaded} {...overrides} />,
    ),
    onUploaded,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AssetUploadControl idle/choosing state', () => {
  it('starts collapsed behind a single, unmistakable "Upload video" button', () => {
    const { getByRole, queryByLabelText } = renderControl()
    expect(getByRole('button', { name: 'Upload video' })).toBeTruthy()
    expect(queryByLabelText('Video file')).toBeNull()
  })

  it('expands to a labeled file input and title field on click', () => {
    const { getByRole, getByLabelText } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    expect(getByLabelText('Video file')).toBeTruthy()
    expect(getByLabelText('Title')).toBeTruthy()
  })

  it('names every accepted type up front', () => {
    const { getByRole, getByText } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    expect(getByText(/MP4, MOV, MKV, WebM, AVI, or MPEG-TS/)).toBeTruthy()
  })
})

describe('AssetUploadControl unsupported file type', () => {
  it('rejects an unsupported extension immediately, before any network call, naming the accepted types', () => {
    const { getByRole, getByLabelText, getByText } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    const fileInput = getByLabelText('Video file') as HTMLInputElement
    const badFile = new File(['x'], 'meeting.pdf', { type: 'application/pdf' })
    fireEvent.change(fileInput, { target: { files: [badFile] } })

    expect(
      getByText(/is not a supported video file\. Accepted types: MP4, MOV, MKV, WebM, AVI, or MPEG-TS\./),
    ).toBeTruthy()
    expect(uploadAssetFileWithProgress).not.toHaveBeenCalled()
    // Submit stays unreachable -- no valid file is staged.
    expect((getByRole('button', { name: 'Upload' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('AssetUploadControl uploading / progress / success / failure', () => {
  it('walks choosing -> uploading (with progress) -> success, and the file appears via onUploaded', async () => {
    let resolveUpload: (value: UploadedAssetResponse) => void = () => {}
    let capturedProgress: ((percent: number) => void) | undefined
    vi.mocked(uploadAssetFileWithProgress).mockImplementation((_payload, onProgress) => {
      capturedProgress = onProgress
      return new Promise((resolve) => {
        resolveUpload = resolve
      })
    })

    const { getByRole, getByLabelText, getByText, findByText, onUploaded } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    fireEvent.change(getByLabelText('Video file'), { target: { files: [mp4()] } })
    fireEvent.change(getByLabelText('Title'), { target: { value: 'City Council' } })
    fireEvent.click(getByRole('button', { name: 'Upload' }))

    // Two elements carry the "uploading" text on purpose: a visible <span>
    // and a screen-reader-only aria-live status announcing the same thing.
    expect(getByText(/Uploading council-meeting\.mp4/, { selector: 'span' })).toBeTruthy()
    expect(uploadAssetFileWithProgress).toHaveBeenCalledOnce()

    capturedProgress?.(42)
    expect(await findByText('42%')).toBeTruthy()

    resolveUpload({
      asset_id: 'city-council-abc123',
      title: 'City Council',
      state: 'pending_ingest',
      file_path: '/uploads/city-council-abc123/council-meeting.mp4',
      file_size_bytes: 12,
    })

    expect(await findByText('Uploaded: City Council')).toBeTruthy()
    expect(onUploaded).toHaveBeenCalledWith(
      expect.objectContaining({ asset_id: 'city-council-abc123' }),
    )
  })

  it('shows a plain-language failure reason and lets the operator try again', async () => {
    vi.mocked(uploadAssetFileWithProgress).mockRejectedValue(
      new ApiError(
        'Request failed: 422',
        422,
        "Video codec 'mpeg2video' is not supported. Supported codecs: av1, h264, hevc, prores, vp8, vp9.",
      ),
    )

    const { getByRole, getByLabelText, findByText } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    fireEvent.change(getByLabelText('Video file'), { target: { files: [mp4()] } })
    fireEvent.change(getByLabelText('Title'), { target: { value: 'City Council' } })
    fireEvent.click(getByRole('button', { name: 'Upload' }))

    expect(
      await findByText(/Video codec 'mpeg2video' is not supported/),
    ).toBeTruthy()
    // The retry affordance reflects the failure, not a generic label.
    expect(await findByText('Try again')).toBeTruthy()
  })

  it('lets the operator cancel an in-flight upload', async () => {
    let capturedSignal: AbortSignal | undefined
    vi.mocked(uploadAssetFileWithProgress).mockImplementation(
      (_payload, _onProgress, signal) =>
        new Promise((_resolve, reject) => {
          capturedSignal = signal
          signal?.addEventListener('abort', () => reject(new Error('aborted')))
        }),
    )

    const { getByRole, getByLabelText, findByRole } = renderControl()
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    fireEvent.change(getByLabelText('Video file'), { target: { files: [mp4()] } })
    fireEvent.click(getByRole('button', { name: 'Upload' }))

    fireEvent.click(await findByRole('button', { name: 'Cancel' }))
    expect(capturedSignal?.aborted).toBe(true)
    // Cancelling returns to a state where the operator can upload again,
    // not stuck on a spinner forever.
    expect(await findByRole('button', { name: 'Upload' })).toBeTruthy()
  })
})

describe('AssetUploadControl role gating', () => {
  it('never hides the control for an operator without upload rights -- it stays visible and disabled with a reason', () => {
    const { getByRole, getByText } = renderControl({ canUpload: false, roleCheckReady: true })
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    expect(
      getByText(
        'A records clerk, meeting operator, or support administrator role is required to upload video.',
      ),
    ).toBeTruthy()
    expect((getByRole('button', { name: 'Upload' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not show a denial message before the role check has resolved', () => {
    const { getByRole, queryByText } = renderControl({ canUpload: false, roleCheckReady: false })
    fireEvent.click(getByRole('button', { name: 'Upload video' }))
    expect(queryByText(/role is required/)).toBeNull()
  })
})
