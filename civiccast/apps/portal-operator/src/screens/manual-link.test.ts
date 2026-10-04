// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { describe, expect, it } from 'vitest'

import { manualLink } from './manual-link'

describe('manualLink', () => {
  it('builds a /help#<id> href', () => {
    expect(manualLink('cdn-and-provider-options')).toBe('/help#cdn-and-provider-options')
  })

  it('builds a distinct href per section id', () => {
    expect(manualLink('app-glossary')).toBe('/help#app-glossary')
    expect(manualLink('configuration-storage')).toBe('/help#configuration-storage')
  })
})
