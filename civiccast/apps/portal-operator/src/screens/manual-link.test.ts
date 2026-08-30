// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { manualLink } from './manual-link'

describe('manualLink', () => {
  it('builds a /help#<id> href', () => {
    expect(manualLink('provider-cloudflare-r2')).toBe('/help#provider-cloudflare-r2')
  })

  it('builds a distinct href per section id', () => {
    expect(manualLink('glossary')).toBe('/help#glossary')
    expect(manualLink('where-recordings-live')).toBe('/help#where-recordings-live')
  })
})
