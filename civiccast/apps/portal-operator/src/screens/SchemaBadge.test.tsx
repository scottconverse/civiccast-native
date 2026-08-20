import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'

import type { EgressSchemaCurrency } from '../api/client'
import { SchemaBadge } from './SystemHealthScreen'

const base: EgressSchemaCurrency = {
  channel_id: 'gov',
  current_schema_version: 1,
  sample_schema_version: 1,
  is_current: true,
  proof_events_appended_since_last_sample: 3,
  latest_sampled_at: '2026-06-14T12:00:00Z',
}

describe('SchemaBadge', () => {
  it('renders nothing when there is no schema data', () => {
    const { container } = render(<SchemaBadge schema={undefined} />)
    expect(container.textContent).toBe('')
  })

  it('shows a neutral "No sample yet" — never a confident green — with no sample', () => {
    const { container } = render(
      <SchemaBadge schema={{ ...base, latest_sampled_at: null, is_current: true }} />,
    )
    expect(container.textContent).toContain('No sample yet')
    expect(container.textContent).not.toContain('Schema OK')
  })

  it('shows "Schema OK" with the proof-churn line when current', () => {
    const { container } = render(<SchemaBadge schema={{ ...base, is_current: true }} />)
    expect(container.textContent).toContain('Schema OK')
    expect(container.textContent).toContain('3 proof events since last sample')
  })

  it('shows "Schema drift" with the version-mismatch guidance when drifted', () => {
    const { container } = render(
      <SchemaBadge
        schema={{ ...base, is_current: false, sample_schema_version: 2, current_schema_version: 1 }}
      />,
    )
    expect(container.textContent).toContain('Schema drift')
    expect(container.textContent).toContain('v2')
    expect(container.textContent).toContain('v1')
    expect(container.textContent).toContain('re-migrate')
  })

  it('singularizes the proof-event line for a count of 1', () => {
    const { container } = render(
      <SchemaBadge schema={{ ...base, proof_events_appended_since_last_sample: 1 }} />,
    )
    expect(container.textContent).toContain('1 proof event since last sample')
    expect(container.textContent).not.toContain('1 proof events')
  })
})
