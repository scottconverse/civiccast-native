// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Tiny hash router for the public portal (issue #107).
//
// Hash routing keeps the portal deployable on any static host with zero
// rewrite rules (the operator console uses the same convention), and every
// view — including browse state like `#/recordings?q=council&page=2` — is a
// canonical shareable URL. Hand-rolled on purpose: three routes do not need
// a router dependency in a bundle residents may load on slow connections.

import { useEffect, useState } from 'react'

export type PortalRoute =
  | { view: 'home' }
  | {
      view: 'recordings'
      query: string
      year: string
      body: string
      // S22: custom-field facet filters, keyed by the field's machine key.
      // `#/recordings?cf.meeting_type=Regular` → { meeting_type: 'Regular' }.
      cf: Record<string, string>
      page: number
    }
  | { view: 'watch'; assetId: string }
  | { view: 'schedule'; channel: string }

export function parseHashRoute(hash: string): PortalRoute {
  const raw = hash.replace(/^#/, '')
  const [path, queryString = ''] = raw.split('?', 2)
  const segments = path.split('/').filter(Boolean)
  if (segments[0] === 'recordings') {
    const params = new URLSearchParams(queryString)
    const page = Number.parseInt(params.get('page') ?? '1', 10)
    const cf: Record<string, string> = {}
    for (const [k, v] of params) {
      if (k.startsWith('cf.')) cf[k.slice(3)] = v
    }
    return {
      view: 'recordings',
      query: params.get('q') ?? '',
      year: params.get('year') ?? '',
      body: params.get('body') ?? '',
      cf,
      page: Number.isFinite(page) && page >= 1 ? page : 1,
    }
  }
  if (segments[0] === 'watch' && segments[1]) {
    return { view: 'watch', assetId: decodeURIComponent(segments[1]) }
  }
  if (segments[0] === 'schedule') {
    const params = new URLSearchParams(queryString)
    return { view: 'schedule', channel: params.get('channel') ?? 'public' }
  }
  return { view: 'home' }
}

export function buildRecordingsHash(state: {
  query?: string
  year?: string
  body?: string
  cf?: Record<string, string>
  page?: number
}): string {
  const params = new URLSearchParams()
  if (state.query) params.set('q', state.query)
  if (state.year) params.set('year', state.year)
  if (state.body) params.set('body', state.body)
  // S22: write each custom-field facet back as cf.<key>=<value> so the filtered
  // view is a shareable URL (matches /api/public/search?cf.<key>=<value>).
  for (const [key, value] of Object.entries(state.cf ?? {})) {
    if (value) params.set(`cf.${key}`, value)
  }
  if (state.page && state.page > 1) params.set('page', String(state.page))
  const suffix = params.toString()
  return suffix ? `#/recordings?${suffix}` : '#/recordings'
}

export function buildWatchHash(assetId: string): string {
  return `#/watch/${encodeURIComponent(assetId)}`
}

export function buildScheduleHash(channel?: string): string {
  return channel && channel !== 'public'
    ? `#/schedule?channel=${encodeURIComponent(channel)}`
    : '#/schedule'
}

export function useHashRoute(): PortalRoute {
  const [route, setRoute] = useState<PortalRoute>(() => parseHashRoute(window.location.hash))
  useEffect(() => {
    const onHashChange = () => setRoute(parseHashRoute(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  return route
}
