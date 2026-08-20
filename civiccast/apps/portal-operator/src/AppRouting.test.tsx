import { describe, expect, it } from 'vitest'

import { canonicalRoutePath, isTrimEditorRoute, routeForPath, routePath } from './routes'

describe('operator route aliases', () => {
  it.each([
    ['/cg-designer', '/cg-board', 'cgdesigner'],
    ['/program-guide', '/guide', 'guide'],
    ['/contributors', '/contribute', 'contribute'],
    ['/review-queue', '/review', 'review'],
    ['/summary-review', '/summary', 'summary'],
    ['/epg-export', '/epg', 'epg'],
    ['/readiness', '/health', 'health'],
    ['/today', '/schedule', 'schedule'],
    ['/archive', '/assets', 'assets'],
    ['/subscribers', '/paywall', 'paywall'],
    ['/login', '/setup', 'setup'],
    ['/sign-in', '/setup', 'setup'],
  ] as const)('maps %s to %s', (alias, canonical, routeId) => {
    expect(canonicalRoutePath(alias)).toBe(canonical)
    expect(routeForPath(alias)).toBe(routeId)
  })

  it('keeps canonical route ids stable for shell navigation', () => {
    expect(routePath('health')).toBe('/health')
    expect(routePath('cgdesigner')).toBe('/cg-board')
    expect(routeForPath('/assets/example-recording')).toBe('assets')
    expect(routeForPath('/assets/example-recording/trim')).toBe('assets')
    expect(routeForPath('/does-not-exist')).toBeNull()
  })

  it('recognizes the trim editor as a full-screen route outside the shell', () => {
    expect(isTrimEditorRoute('/assets/example-recording/trim')).toBe(true)
    expect(isTrimEditorRoute('/assets/example-recording')).toBe(false)
    expect(isTrimEditorRoute('/assets')).toBe(false)
  })
})
