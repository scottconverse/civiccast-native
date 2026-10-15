// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useEffect, useState } from 'react'

import { verifyMagicLink } from './api'
import { EMAIL_STORAGE_KEY } from './PaywallGate'

export function MagicLinkVerificationScreen({ token }: { token: string | null }) {
  const [state, setState] = useState<'pending' | 'ok' | 'error'>(token ? 'pending' : 'error')

  useEffect(() => {
    if (!token) return
    let cancelled = false
    verifyMagicLink(token)
      .then((result) => {
        if (cancelled || !result.email) {
          if (!cancelled) setState('error')
          return
        }
        try {
          window.sessionStorage.setItem(EMAIL_STORAGE_KEY, result.email)
        } catch {
          // Private browsing may deny storage. Redemption still succeeded.
        }
        window.history.replaceState(null, '', `${window.location.pathname}#/paywall/verify`)
        setState('ok')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })
    return () => { cancelled = true }
  }, [token])

  return (
    <section className="space-y-4 text-sm">
      <h2 tabIndex={-1} className="text-xl font-semibold">CivicCast access link</h2>
      {state === 'pending' && <p role="status">Checking your link…</p>}
      {state === 'ok' && <p role="status">Your link is active. Browse recordings to choose what to watch.</p>}
      {state === 'error' && <p role="alert">This link could not be used. Open a recording and request a new link.</p>}
      <a href="#/recordings" className="text-emerald-200 underline">Browse recordings</a>
    </section>
  )
}
