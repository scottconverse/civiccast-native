// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { useEffect, useState } from 'react'
import { verifyMagicLink } from '../api'

type RedeemState = 'checking' | 'confirmed' | 'failed'

export function MagicLinkRedeemScreen() {
  const query = window.location.hash.split('?', 2)[1] ?? ''
  const token = new URLSearchParams(query).get('token')
  const [state, setState] = useState<RedeemState>(token ? 'checking' : 'failed')

  useEffect(() => {
    if (!token) return
    let active = true
    verifyMagicLink(token)
      .then((result) => {
        if (!active) return
        if (!result.email) {
          setState('failed')
          return
        }
        try {
          window.sessionStorage.setItem('civiccast.paywall.email', result.email)
          const url = new URL(window.location.href)
          url.searchParams.delete('token')
          url.hash = '#/redeem'
          window.history.replaceState(null, '', url.toString())
          setState('confirmed')
        } catch {
          setState('failed')
        }
      })
      .catch(() => {
        if (active) setState('failed')
      })
    return () => {
      active = false
    }
  }, [token])

  return (
    <section aria-live="polite" className="mx-auto max-w-2xl px-4 py-8">
      <h2 className="text-2xl font-semibold">Sign in to CivicCast</h2>
      {state === 'checking' ? <p>Checking your sign-in link…</p> : null}
      {state === 'confirmed' ? (
        <p>Your sign-in link is confirmed. <a href="#/recordings">Browse recordings</a>.</p>
      ) : null}
      {state === 'failed' ? (
        <p>This link could not be verified. Open a recording and request a new sign-in link.</p>
      ) : null}
    </section>
  )
}
