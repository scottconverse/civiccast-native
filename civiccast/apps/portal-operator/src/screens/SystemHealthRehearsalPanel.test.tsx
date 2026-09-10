// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { RehearsalReport } from '../types/api.generated'
import { RehearsalPanel } from './SystemHealthScreen'
import { healthCheckAnchorId } from './health-check-anchor'

afterEach(cleanup)

// beta.5 walkthrough F-21: the readiness headline said "Do not broadcast yet.
// Private rehearsal is blocked because a required broadcast item is not
// ready" while the detail lines said the rehearsal ran, passed preflight,
// finalized a recording and loaded the resident preview. The card now
// separates "Rehearsal result" from "Broadcast gate" and names the blocker.
function report(overrides: Partial<RehearsalReport> = {}): RehearsalReport {
  return {
    rehearsal_id: 'rehearsal-abc',
    started_at: '2026-09-09T12:00:00Z',
    status: 'blocked',
    safe_to_broadcast: 'red',
    rehearsal_result: 'passed',
    gate: {
      color: 'red',
      blocking: [
        {
          id: 'backup-status',
          label: 'Backup destination',
          color: 'red',
          next_step: 'Choose Backup destination in Setup.',
        },
      ],
      attention: [],
      summary: '1 required item not ready: Backup destination.',
    },
    message:
      'Rehearsal passed, but the broadcast gate has 1 required item not ready: Backup destination.',
    resident_preview: { status: 'available', public_url: 'https://meetings.example.gov' } as RehearsalReport['resident_preview'],
    checks: [],
    private_session_id: 'rehearsal-abc',
    recording_asset_id: 'rehearsal-abc',
    resident_preview_proof: 'Resident preview loaded https://meetings.example.gov',
    evidence: ['Live preflight passed for the selected sample.', 'Recording finalized.'],
    next_step:
      'Fix Backup destination (Choose Backup destination in Setup), then run the check again.',
    ...overrides,
  }
}

describe('RehearsalPanel (F-21)', () => {
  it('separates a passed rehearsal from a red gate and names the blocking item with a link', () => {
    const { getByTestId, getByRole, getByText, queryByText } = render(
      <RehearsalPanel report={report()} />,
    )

    const block = getByTestId('rehearsal-result-and-gate')
    expect(block.textContent).toContain('Rehearsal result:')
    expect(block.textContent).toContain('Passed')
    expect(block.textContent).toContain('Broadcast gate:')
    expect(block.textContent).toContain('1 required item not ready')

    const link = getByRole('link', { name: 'Backup destination' })
    expect(link.getAttribute('href')).toBe(`#${healthCheckAnchorId('backup-status')}`)
    expect(block.textContent).toContain('Choose Backup destination in Setup.')

    // The headline pill still says do-not-broadcast (the gate is red), but the
    // message no longer calls the rehearsal itself "blocked".
    expect(getByText('Do not broadcast yet')).toBeTruthy()
    expect(queryByText(/Private rehearsal is blocked/)).toBeNull()
    expect(getByText(/Rehearsal passed, but the broadcast gate/)).toBeTruthy()
  })

  it('reports a rehearsal that never ran as "Not run" alongside the gate', () => {
    const { getByTestId } = render(
      <RehearsalPanel
        report={report({
          rehearsal_result: 'not_run',
          private_session_id: null,
          recording_asset_id: null,
          resident_preview_proof: null,
          evidence: ['Upload storage is not configured.'],
          message: 'Private rehearsal is blocked because upload storage is not ready.',
        })}
      />,
    )

    const block = getByTestId('rehearsal-result-and-gate')
    expect(block.textContent).toContain('Not run')
    expect(block.textContent).toContain('1 required item not ready')
  })

  it('shows a green gate with all required items ready and no item list', () => {
    const { getByTestId, queryByRole } = render(
      <RehearsalPanel
        report={report({
          status: 'ready',
          safe_to_broadcast: 'green',
          gate: { color: 'green', blocking: [], attention: [], summary: 'All required items are ready.' },
          message: 'Private rehearsal checks passed. The station can run the first broadcast flow.',
          next_step: 'Use Run Meeting for the live event and keep System Health open.',
        })}
      />,
    )

    const block = getByTestId('rehearsal-result-and-gate')
    expect(block.textContent).toContain('All required items ready')
    expect(queryByRole('link')).toBeNull()
  })

  it('lists yellow required items when nothing blocks but live proof is missing', () => {
    const { getByTestId, getByRole } = render(
      <RehearsalPanel
        report={report({
          status: 'needs_attention',
          safe_to_broadcast: 'yellow',
          gate: {
            color: 'yellow',
            blocking: [],
            attention: [
              {
                id: 'source-preflight',
                label: 'Camera or meeting source',
                color: 'yellow',
                next_step: 'Run the private rehearsal with the real source.',
              },
            ],
            summary:
              '1 required item still needs attention before the public broadcast: Camera or meeting source.',
          },
          message:
            'Private rehearsal ran, but a required item still needs live proof before the public broadcast.',
        })}
      />,
    )

    expect(getByTestId('rehearsal-result-and-gate').textContent).toContain(
      '1 required item needs attention',
    )
    expect(getByRole('link', { name: 'Camera or meeting source' })).toBeTruthy()
  })
})
