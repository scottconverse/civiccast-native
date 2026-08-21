import type { RouteId } from './components/shell/Sidebar'
import { matchPath } from 'react-router'

export const ROUTE_PATHS: Record<RouteId, string> = {
  setup: '/setup',
  live: '/live',
  facility: '/facility',
  controlroom: '/control-room',
  controlroomsetup: '/control-room-setup',
  remotecontribution: '/remote-contribution',
  channels: '/channels',
  cg: '/cg',
  cgdesigner: '/cg-board',
  today: '/today',
  schedule: '/schedule',
  autoschedule: '/auto-schedule',
  guide: '/guide',
  assets: '/assets',
  contribute: '/contribute',
  review: '/review',
  summary: '/summary',
  publish: '/publish',
  playback: '/playback-policy',
  analytics: '/analytics',
  appadmin: '/app-admin',
  archive: '/archive',
  subscribers: '/subscribers',
  activitypub: '/activitypub',
  health: '/health',
  alerts: '/alerts',
  eas: '/emergency-alerts',
  'ai-models': '/ai-models',
  'custom-fields': '/custom-fields',
  reports: '/reports',
  epg: '/epg',
  underwriting: '/underwriting',
  agendas: '/agendas',
  paywall: '/paywall',
  recording: '/recording',
  missingmedia: '/missing-media',
  medialifecycle: '/media-lifecycle',
}

export const ROUTE_ALIASES: Record<string, string> = {
  '/cg-designer': '/cg-board',
  '/program-guide': '/guide',
  '/contributors': '/contribute',
  '/review-queue': '/review',
  '/summary-review': '/summary',
  '/epg-export': '/epg',
  '/readiness': '/health',
  '/today': '/schedule',
  '/archive': '/assets',
  '/subscribers': '/paywall',
  // F-RC3-5 (nav): First Setup hosts the returning-operator sign-in, so a
  // guessed /login or /sign-in lands there instead of Page not found.
  '/login': '/setup',
  '/sign-in': '/setup',
}

export function canonicalRoutePath(pathname: string): string {
  return ROUTE_ALIASES[pathname] ?? pathname
}

export function routeForPath(pathname: string): RouteId | null {
  const canonical = canonicalRoutePath(pathname)
  if (canonical.startsWith('/assets')) return 'assets'
  const found = Object.entries(ROUTE_PATHS).find(([, path]) => path === canonical)
  return found ? found[0] as RouteId : null
}

export function routePath(route: RouteId): string {
  return ROUTE_PATHS[route] ?? '/setup'
}

export function isTrimEditorRoute(pathname: string): boolean {
  return Boolean(matchPath('/assets/:assetId/trim', pathname))
}
