// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * Field evidence (native beta candidate #17): the live room used to show
 * the backend's internal reason code verbatim ("Resolve network.not_probed
 * and re-run pre-flight"). `preflightNextStep` is the only thing standing
 * between a raw backend reason code and the operator's screen -- these
 * tests pin that it never falls through to printing the code itself.
 */

import { describe, expect, it } from 'vitest'

import { PREFLIGHT_NEXT_STEP, preflightNextStep } from './live'

describe('preflightNextStep', () => {
  it('returns a mapped, plain-English action for every known reason code', () => {
    for (const code of Object.keys(PREFLIGHT_NEXT_STEP)) {
      const text = preflightNextStep(code)
      expect(text).toBe(PREFLIGHT_NEXT_STEP[code])
      expect(text).not.toContain(code)
    }
  })

  it('never echoes an unrecognized reason code back onto the screen', () => {
    const text = preflightNextStep('some.future_reason_code')
    expect(text).not.toContain('some.future_reason_code')
    expect(text.length).toBeGreaterThan(0)
  })

  it('handles a missing reason code without throwing', () => {
    expect(preflightNextStep(null)).not.toHaveLength(0)
    expect(preflightNextStep(undefined)).not.toHaveLength(0)
  })
})
