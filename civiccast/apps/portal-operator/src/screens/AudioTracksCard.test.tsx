// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { AudioProgramTrack } from '../types/api.generated'
import { AudioTracksView } from './AudioTracksCard'

afterEach(cleanup)

function track(overrides: Partial<AudioProgramTrack> = {}): AudioProgramTrack {
  return {
    track_id: 't_sap',
    scope: 'channel',
    target_id: 'gov',
    kind: 'sap',
    language: 'es',
    label: 'Spanish SAP',
    enabled: true,
    ...overrides,
  } as AudioProgramTrack
}

describe('AudioTracksView', () => {
  it('lists secondary audio tracks with kind + language', () => {
    const { container } = render(
      <AudioTracksView
        tracks={[track(), track({ track_id: 't_desc', kind: 'descriptive', language: 'en', label: 'Audio description' })]}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('Spanish SAP')
    expect(text).toContain('SAP')
    expect(text).toContain('Descriptive')
    expect(text).toContain('Audio description')
  })

  it('states single-program when there are no secondary tracks', () => {
    const { container } = render(<AudioTracksView tracks={[]} />)
    expect(container.textContent ?? '').toContain('Single audio program')
  })

  it('shows a loading state instead of a false zero-state while fetching', () => {
    const { container } = render(<AudioTracksView tracks={undefined} loading />)
    const text = container.textContent ?? ''
    expect(text).toContain('Loading audio tracks')
    expect(text).not.toContain('Single audio program')
  })

  it('surfaces a load error', () => {
    const { getByRole } = render(<AudioTracksView tracks={undefined} error={new Error('boom')} />)
    expect(getByRole('alert').textContent).toContain('Could not load audio tracks')
  })
})
