import { describe, expect, it } from 'vitest'

import type { StoreSubmissionMetadata } from '../types/api.generated'
import { formatBuiltAt, humanize, shortSha, submissionSummary } from './app-admin-format'

describe('app-admin-format', () => {
  it('humanize replaces underscores', () => {
    expect(humanize('android_tv')).toBe('android tv')
    expect(humanize('pending_review')).toBe('pending review')
  })

  it('shortSha takes the first 12 chars', () => {
    expect(shortSha('a'.repeat(64))).toBe('a'.repeat(12))
  })

  it('formatBuiltAt is robust to a bad value', () => {
    expect(formatBuiltAt('not-a-date')).toBe('not-a-date')
    expect(formatBuiltAt('2026-06-01T18:00:00Z')).not.toBe('2026-06-01T18:00:00Z')
  })

  it('submissionSummary names status, version, package', () => {
    const sub: StoreSubmissionMetadata = {
      app_target: 'roku',
      version_code: 1,
      version_name: '0.1.0',
      submission_status: 'pending_review',
      package_id: 'tv.civiccast.roku',
    }
    const summary = submissionSummary(sub)
    expect(summary).toContain('pending review')
    expect(summary).toContain('v0.1.0')
    expect(summary).toContain('tv.civiccast.roku')
  })
})
