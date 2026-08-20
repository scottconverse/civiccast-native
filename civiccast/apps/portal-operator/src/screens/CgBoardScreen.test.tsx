import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { CgPortalDisplay, CgTemplate } from '../types/api.generated'
import { LayoutPreview, OutputPanel } from './CgBoardScreen'

// vitest config has no global afterEach, so testing-library's auto-cleanup
// never registers -- unmount each render so body-scoped queries don't see
// elements left behind by the previous test.
afterEach(cleanup)

const TEMPLATE: CgTemplate = {
  template_id: 'tpl-board-v1',
  label: 'Fullscreen board with ticker',
  regions: [{ region: 'main', zone_kind: 'primary', order: 0 }],
}

const DISPLAY = {
  channel_id: 'public',
  snapshot: {
    snapshot_id: 'snap-1',
    generated_at: '2026-08-06T12:00:00Z',
    channel_id: 'public',
    template: TEMPLATE,
    zones: [],
    hls_render_path: '/var/civiccast/hls/public',
    portal_render_path: '/var/civiccast/portal/public/board.json',
    proof_boundary: 'S6 V1',
  },
  render_plan: {
    channel_id: 'public',
    snapshot_url: 'https://cdn.example.org/public/snapshot.json',
    manifest_url: 'https://cdn.example.org/public/live.m3u8',
    segment_pattern: 'seg-%05d.ts',
    target_duration_seconds: 6,
    linear_overlay_contract_url: 'https://cdn.example.org/public/overlay.json',
    proof_boundary: 'S6 V1',
  },
} as unknown as CgPortalDisplay

describe('LayoutPreview', () => {
  it('shows human-readable loading copy, not raw placeholder tokens, before data arrives', () => {
    // Gate finding m-1: `template?.template_id ?? 'loading-template'` and
    // `display?.snapshot.proof_boundary ?? 'loading'` used to leak technical
    // placeholder tokens straight to the operator during transient states.
    const { getByText, queryByText } = render(
      <LayoutPreview template={undefined} display={undefined} />,
    )
    expect(getByText('Loading template…')).toBeTruthy()
    expect(getByText('Loading…')).toBeTruthy()
    expect(queryByText('loading-template')).toBeNull()
    expect(queryByText('loading')).toBeNull()
  })

  it('shows the real template id and proof boundary once loaded', () => {
    const { getByText } = render(<LayoutPreview template={TEMPLATE} display={DISPLAY} />)
    expect(getByText('tpl-board-v1')).toBeTruthy()
    expect(getByText('S6 V1')).toBeTruthy()
  })
})

describe('OutputPanel', () => {
  it('shows human-readable loading copy before data arrives', () => {
    const { getAllByText, queryByText } = render(<OutputPanel display={undefined} />)
    expect(getAllByText('Loading…')).toHaveLength(3)
    expect(queryByText('loading')).toBeNull()
  })

  it('shows the real output paths once loaded', () => {
    const { getByText } = render(<OutputPanel display={DISPLAY} />)
    expect(getByText('/var/civiccast/portal/public/board.json')).toBeTruthy()
    expect(getByText('https://cdn.example.org/public/live.m3u8')).toBeTruthy()
    expect(getByText('https://cdn.example.org/public/overlay.json')).toBeTruthy()
  })
})
