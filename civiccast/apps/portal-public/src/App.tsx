// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Public portal shell (issue #107): header + nav + hash-route switch.
//
// Views: #/ home, #/recordings (browse/search/pagination — state in the hash
// query so every view is shareable), #/watch/{asset_id} detail. The legacy
// `?manifest=` override keeps its exact pre-#107 behavior: it renders a
// player-only view regardless of route (the installer resident preview and
// clean-room e2e depend on it).

import { useEffect, useMemo, useRef, type MouseEvent as ReactMouseEvent } from 'react'
import { emitAnalyticsEvent } from './analytics'
import { HlsPlayer } from './HlsPlayer'
import { buildRecordingsHash, buildScheduleHash, useHashRoute, type PortalRoute } from './router'
import { ChannelGuideScreen } from './screens/ChannelGuideScreen'
import { HomeScreen } from './screens/HomeScreen'
import { RecordingsScreen } from './screens/RecordingsScreen'
import { WatchScreen } from './screens/WatchScreen'

// Points at the station's own in-product manual (served by the operator
// console at /operator/help, no staff sign-in required -- see
// civiccast/docsite/router.py) rather than straight at a GitHub issue
// template, so reporting a problem never requires a GitHub account. The
// manual's own "Don't Have A GitHub Account?" section still offers the
// GitHub path for whoever wants it.
const BETA_FEEDBACK_URL = '/operator/help#report-without-github'

function getManifestOverride(): string | null {
  return new URLSearchParams(window.location.search).get('manifest')
}

function analyticsSection(route: PortalRoute, manifestOverride: string | null): string {
  if (manifestOverride) return 'watch_manifest_override'
  if (route.view === 'recordings') return 'recordings_browse'
  if (route.view === 'watch') return 'watch_recording'
  if (route.view === 'schedule') return 'channel_guide'
  return 'portal_home'
}

function App() {
  const manifestOverride = useMemo(() => getManifestOverride(), [])
  const route = useHashRoute()
  const lastViewRef = useRef<string | null>(null)

  // Routing analytics (Stage G posture): one privacy-safe `schedule_browse`
  // event per view, fail-silent; see src/analytics.ts.
  useEffect(() => {
    const section = analyticsSection(route, manifestOverride)
    if (lastViewRef.current === section) return
    lastViewRef.current = section
    emitAnalyticsEvent('schedule_browse', { properties: { section } })
  }, [route, manifestOverride])

  // Move focus to the view heading on in-app navigation so screen-reader and
  // keyboard users land on the new content, not stale focus. Gated on real
  // interaction having happened at least once -- mirrors the operator
  // console's identical fix (apps/portal-operator/src/App.tsx,
  // UX-MAJOR-2): a route observed for the first time (e.g. a resident
  // deep-links straight to `#/recordings`) must never steal focus before
  // the resident's first Tab press, or it silently defeats the skip link
  // this same fix adds -- the skip link is only the first Tab target if
  // nothing else claimed focus first.
  //
  // "First route" is tracked with its own ref rather than reusing
  // `lastViewRef` above: that ref is written by the analytics effect,
  // which (being declared first) always runs before this effect in the
  // same commit, so checking it here would see the mount's own route as
  // already "seen" and fire immediately on first render -- exactly the
  // bug this guard exists to prevent.
  const hasInteractedRef = useRef(false)
  useEffect(() => {
    const markInteracted = () => {
      hasInteractedRef.current = true
    }
    window.addEventListener('pointerdown', markInteracted, { capture: true })
    window.addEventListener('keydown', markInteracted, { capture: true })
    return () => {
      window.removeEventListener('pointerdown', markInteracted, true)
      window.removeEventListener('keydown', markInteracted, true)
    }
  }, [])

  const isFirstRouteRef = useRef(true)
  useEffect(() => {
    const wasFirstRoute = isFirstRouteRef.current
    isFirstRouteRef.current = false
    if (wasFirstRoute || !hasInteractedRef.current) return
    const heading = document.querySelector<HTMLElement>('h2[tabindex="-1"]')
    heading?.focus({ preventScroll: false })
  }, [route])

  return (
    <div className="min-h-full bg-civiccast-ink text-civiccast-mist">
      <SkipToContentLink />
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-3 border-b border-white/10 pb-5">
          <div className="flex flex-col gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-200">
              CivicCast Portal
            </p>
            <h1 className="text-2xl font-semibold sm:text-3xl">
              CivicCast public portal
            </h1>
            <p className="max-w-3xl text-sm leading-6 text-stone-300">
              Watch the current broadcast, see upcoming premieres, and replay
              published meetings from the resident archive.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <nav aria-label="Portal sections" className="flex flex-wrap gap-2">
              <NavLink href="#/" current={route.view === 'home'}>
                Home
              </NavLink>
              <NavLink
                href={buildRecordingsHash({})}
                current={route.view === 'recordings' || route.view === 'watch'}
              >
                Recordings
              </NavLink>
              <NavLink href={buildScheduleHash()} current={route.view === 'schedule'}>
                Schedule
              </NavLink>
            </nav>
            <a
              href={BETA_FEEDBACK_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center text-sm font-semibold text-emerald-200 underline decoration-emerald-300/50 underline-offset-4 hover:text-emerald-100"
            >
              Report a beta issue
            </a>
          </div>
          <p className="m-0 text-xs text-stone-400">
            Do not include passwords, recovery codes, staff tokens, or private meeting material in reports.
          </p>
        </header>

        <main id={MAIN_CONTENT_ID} tabIndex={-1}>
          {manifestOverride ? (
            <ManifestOverrideView manifestUrl={manifestOverride} />
          ) : route.view === 'recordings' ? (
            <RecordingsScreen
              query={route.query}
              year={route.year}
              body={route.body}
              cf={route.cf}
              page={route.page}
            />
          ) : route.view === 'watch' ? (
            <WatchScreen assetId={route.assetId} />
          ) : route.view === 'schedule' ? (
            <ChannelGuideScreen channel={route.channel} />
          ) : (
            <HomeScreen />
          )}
        </main>
      </div>
    </div>
  )
}

/** DOM id of the portal's `<main>` landmark. Shared by the skip link's
 *  target (W-3) and the existing route-change focus effect above
 *  (UX-MAJOR-2 precedent this fix's operator-console counterpart mirrors). */
const MAIN_CONTENT_ID = 'main-content'

/** First focusable element on every portal view (W-3, WCAG 2.4.1). Lets
 *  keyboard and screen-reader users jump past the header/nav straight to
 *  the view's own content. Hidden until focused via Tailwind's `sr-only` /
 *  `focus:not-sr-only` pair. */
function SkipToContentLink() {
  // Plain hash navigation would overwrite the app's own routing fragment:
  // this portal parses `window.location.hash` for routing (see router.ts),
  // so activating a bare `href="#main-content"` from `#/recordings`,
  // `#/watch/...`, or `#/schedule` replaces the active route -- the link
  // would silently navigate the resident back to the home view instead of
  // only moving focus. Move focus imperatively and suppress the default
  // hash navigation so the route is left untouched.
  const handleActivate = (event: ReactMouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    document.getElementById(MAIN_CONTENT_ID)?.focus({ preventScroll: false })
  }
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      onClick={handleActivate}
      // Explicit tabIndex=0 (redundant in Chromium/Firefox, required in
      // WebKit/Safari): by default WebKit only puts form controls in the
      // Tab sequence, not plain links, unless "Full Keyboard Access" is on
      // -- without this the skip link would be unreachable by keyboard for
      // every default-configuration Safari user.
      tabIndex={0}
      className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-civiccast-ink focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-emerald-100 focus:ring-2 focus:ring-emerald-300"
    >
      Skip to main content
    </a>
  )
}

function NavLink({
  href,
  current,
  children,
}: {
  href: string
  current: boolean
  children: string
}) {
  return (
    <a
      href={href}
      aria-current={current ? 'page' : undefined}
      className={`inline-flex min-h-11 items-center rounded-md border px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-200 ${
        current
          ? 'border-emerald-300/80 bg-emerald-300/10 text-emerald-100'
          : 'border-stone-500/60 text-stone-100 hover:border-emerald-300/60'
      }`}
    >
      {children}
    </a>
  )
}

function ManifestOverrideView({ manifestUrl }: { manifestUrl: string }) {
  return (
    <section aria-labelledby="live-heading" className="space-y-3">
      <div>
        <h2 id="live-heading" className="text-xl font-semibold">
          Direct video preview
        </h2>
        <p className="text-sm text-stone-300">
          This link may show a live feed or a recording.
        </p>
      </div>
      <HlsPlayer manifestUrl={manifestUrl} analytics={{ contentId: 'manifest-override' }} />
    </section>
  )
}

export default App
