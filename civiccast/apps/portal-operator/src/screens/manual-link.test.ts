// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { manualLink } from './manual-link'

describe('manualLink', () => {
  it('builds a /help#<id> href', () => {
    expect(manualLink('cdn-and-provider-options')).toBe('/help#cdn-and-provider-options')
  })

  it('normalizes legacy section ids to current manual anchors', () => {
    expect(manualLink('glossary')).toBe('/help#app-glossary')
    expect(manualLink('where-recordings-live')).toBe('/help#configuration-storage')
    expect(manualLink('provider-youtube')).toBe('/help#publishing-providers')
    expect(manualLink('provider-cloudflare-r2')).toBe('/help#cdn-and-provider-options')
    expect(manualLink('provider-federation')).toBe('/help#federation-activitypub')
    expect(manualLink('report-without-github')).toBe('/help#report-a-beta-issue')
  })
})
