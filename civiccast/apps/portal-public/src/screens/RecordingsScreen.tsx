// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Browse all published recordings: search + publish-year + meeting-body
// facets + pagination. All browse state lives in the hash query, so every
// view is a shareable URL.
//
// The meeting-body facet (#107 option b) derives its options from the
// values actually in use on published recordings - no fixed vocabulary;
// untagged recordings simply never match a body filter.

import { useEffect, useMemo, useState } from 'react'
import { fetchJson } from '../api'
import { buildRecordingsHash } from '../router'
import { RecordingCard } from './HomeScreen'
import type { AssetMetadata } from '../types'

type LoadState = 'loading' | 'ready' | 'error'

// Module-local on purpose (react-refresh/only-export-components): nothing
// else imports these, and exporting non-components from a screen file breaks
// fast refresh.
const RECORDINGS_PAGE_SIZE = 12

// S22: does an asset carry an exposed custom-field value matching key=value?
function assetMatchesCustomField(asset: AssetMetadata, key: string, value: string): boolean {
  return (asset.custom_fields ?? []).some((cf) => cf.key === key && cf.value === value)
}

// S22: a new facet map with `key` set to `value` (or removed when value is
// empty). Module-local + pure.
function withCustomFieldFilter(
  current: Record<string, string>,
  key: string,
  value: string,
): Record<string, string> {
  const next: Record<string, string> = {}
  for (const [k, v] of Object.entries(current)) {
    if (k !== key && v) next[k] = v
  }
  if (value) next[key] = value
  return next
}

// S22: navigate to a custom-field-filtered recordings view. The hash write +
// the cf-merge live here at module scope so the screen's handler never spreads
// the `cf` prop in the same range as a global write (react-hooks/immutability,
// which only checks inside components/hooks).
function navigateCustomFieldFilter(
  base: { query: string; year: string; body: string; cf: Record<string, string> },
  key: string,
  value: string,
): void {
  const nextCf = withCustomFieldFilter(base.cf, key, value)
  window.location.hash = buildRecordingsHash({
    query: base.query,
    year: base.year,
    body: base.body,
    cf: nextCf,
    page: 1,
  })
}

function filterRecordings(
  recordings: AssetMetadata[],
  query: string,
  year: string,
  body: string,
  cf: Record<string, string>,
): AssetMetadata[] {
  const needle = query.trim().toLowerCase()
  return recordings.filter((asset) => {
    if (year) {
      const published = asset.published_at ? String(new Date(asset.published_at).getFullYear()) : ''
      if (published !== year) return false
    }
    if (body && (asset.meeting_body ?? '') !== body) return false
    // S22: every active custom-field facet must match (AND), mirroring the
    // server-side cf.<key>=<value> exact-match semantics.
    for (const [key, value] of Object.entries(cf)) {
      if (value && !assetMatchesCustomField(asset, key, value)) return false
    }
    if (!needle) return true
    const haystack = `${asset.title} ${asset.description ?? ''}`.toLowerCase()
    return haystack.includes(needle)
  })
}

export function RecordingsScreen({
  query,
  year,
  body,
  cf,
  page,
}: {
  query: string
  year: string
  body: string
  cf: Record<string, string>
  page: number
}) {
  const [state, setState] = useState<LoadState>('loading')
  const [recordings, setRecordings] = useState<AssetMetadata[]>([])
  const [retryKey, setRetryKey] = useState(0)
  // The search box mirrors the hash-route query until the resident types;
  // keying local edits by the query they started from replaces the old
  // sync-from-props effect (react-hooks/set-state-in-effect).
  const [searchEdit, setSearchEdit] = useState<{ base: string; value: string } | null>(null)
  const searchInput = searchEdit?.base === query ? searchEdit.value : query

  useEffect(() => {
    let cancelled = false
    // S22: fetch the public-search projection, which carries each asset's
    // exposed (searchable && api_exposed) custom-field values — the same
    // packaged corpus /api/public/assets returns, plus custom_fields for the
    // facets. We pull the full set once and filter in-browser, matching the
    // existing meeting-body facet convention (the exposure boundary is enforced
    // server-side in the response model, never client-side).
    fetchJson<AssetMetadata[]>('/api/public/search')
      .then((result) => {
        if (cancelled) return
        setRecordings(result)
        setState('ready')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [retryKey])

  function retryLoad() {
    setState('loading')
    setRetryKey((value) => value + 1)
  }

  const years = useMemo(() => {
    const seen = new Set<string>()
    for (const asset of recordings) {
      if (asset.published_at) {
        seen.add(String(new Date(asset.published_at).getFullYear()))
      }
    }
    return [...seen].sort((a, b) => b.localeCompare(a))
  }, [recordings])

  const bodies = useMemo(() => {
    const seen = new Set<string>()
    for (const asset of recordings) {
      if (asset.meeting_body) seen.add(asset.meeting_body)
    }
    return [...seen].sort((a, b) => a.localeCompare(b))
  }, [recordings])

  // S22: derive each searchable custom-field facet (key → label + the distinct
  // values in use), exactly like the body/year facets. No fixed vocabulary —
  // only exposed values that arrive on the search projection appear.
  const customFieldFacets = useMemo(() => {
    const byKey = new Map<string, { label: string; values: Set<string> }>()
    for (const asset of recordings) {
      for (const cfv of asset.custom_fields ?? []) {
        const entry = byKey.get(cfv.key) ?? { label: cfv.label, values: new Set<string>() }
        if (cfv.value) entry.values.add(cfv.value)
        byKey.set(cfv.key, entry)
      }
    }
    return [...byKey.entries()]
      .map(([key, { label, values }]) => ({
        key,
        label,
        values: [...values].sort((a, b) => a.localeCompare(b)),
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [recordings])

  const filtered = useMemo(
    () => filterRecordings(recordings, query, year, body, cf),
    [recordings, query, year, body, cf],
  )
  const pageCount = Math.max(1, Math.ceil(filtered.length / RECORDINGS_PAGE_SIZE))
  const currentPage = Math.min(page, pageCount)
  const pageItems = filtered.slice(
    (currentPage - 1) * RECORDINGS_PAGE_SIZE,
    currentPage * RECORDINGS_PAGE_SIZE,
  )

  function applySearch(nextQuery: string) {
    window.location.hash = buildRecordingsHash({ query: nextQuery, year, body, cf, page: 1 })
  }

  function applyYear(nextYear: string) {
    window.location.hash = buildRecordingsHash({ query, year: nextYear, body, cf, page: 1 })
  }

  function applyBody(nextBody: string) {
    window.location.hash = buildRecordingsHash({ query, year, body: nextBody, cf, page: 1 })
  }

  // S22: set/clear one custom-field facet (empty value removes the filter).
  function applyCf(key: string, value: string) {
    navigateCustomFieldFilter({ query, year, body, cf }, key, value)
  }

  function goToPage(nextPage: number) {
    window.location.hash = buildRecordingsHash({ query, year, body, cf, page: nextPage })
  }

  return (
    <section aria-labelledby="browse-heading" className="space-y-5">
      <div>
        <h2 id="browse-heading" tabIndex={-1} className="text-xl font-semibold">
          Browse recordings
        </h2>
        <p className="mt-1 text-sm text-stone-300">
          Search and replay every published meeting recording. Each page,
          search, and recording has its own shareable link.
        </p>
      </div>

      <form
        role="search"
        className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]"
        onSubmit={(event) => {
          event.preventDefault()
          applySearch(searchInput)
        }}
      >
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-stone-100">Search recordings</span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) =>
              setSearchEdit({ base: query, value: event.currentTarget.value })
            }
            placeholder="Search by title or description"
            className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-stone-100">Year</span>
          <select
            value={year}
            onChange={(event) => applyYear(event.currentTarget.value)}
            className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          >
            <option value="">All years</option>
            {/* Audit UX-001 twin: same ghost-filter guard as the body facet. */}
            {year && !years.includes(year) && (
              <option value={year}>{year} (no recordings)</option>
            )}
            {years.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-stone-100">Meeting body</span>
          <select
            value={body}
            onChange={(event) => applyBody(event.currentTarget.value)}
            className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          >
            <option value="">All bodies</option>
            {/* Audit UX-001: a deep-linked value with no matching data must
                stay visible and selectable-away, not silently render as
                "All bodies" while the filter quietly excludes everything. */}
            {body && !bodies.includes(body) && (
              <option value={body}>{body} (no recordings)</option>
            )}
            {bodies.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="min-h-11 self-end rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200"
        >
          Search
        </button>
      </form>

      {/* S22: one accessible facet (S20) per searchable custom field in use. */}
      {customFieldFacets.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {customFieldFacets.map((facet) => {
            const selected = cf[facet.key] ?? ''
            return (
              <label key={facet.key} className="grid gap-1 text-sm">
                <span className="font-medium text-stone-100">{facet.label}</span>
                <select
                  aria-label={facet.label}
                  value={selected}
                  onChange={(event) => applyCf(facet.key, event.currentTarget.value)}
                  className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
                >
                  <option value="">All</option>
                  {/* UX-001 twin: a deep-linked value with no matching data stays
                      visible and selectable-away rather than silently excluding all. */}
                  {selected && !facet.values.includes(selected) && (
                    <option value={selected}>{selected} (no recordings)</option>
                  )}
                  {facet.values.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            )
          })}
        </div>
      )}

      {state === 'loading' && (
        <p
          role="status"
          aria-live="polite"
          className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-200"
        >
          Loading published recordings.
        </p>
      )}

      {state === 'error' && (
        <div
          role="alert"
          className="rounded-lg border border-red-400/50 bg-red-950/40 p-5 text-sm text-red-100"
        >
          <p>Published recordings could not be loaded. Try again or contact the station.</p>
          <button
            type="button"
            onClick={retryLoad}
            className="mt-3 min-h-11 rounded-md border border-red-200/70 px-4 py-2 font-semibold hover:bg-red-200/10 focus:outline-none focus:ring-2 focus:ring-red-100"
          >
            Retry
          </button>
        </div>
      )}

      {state === 'ready' && filtered.length === 0 && (
        <p className="rounded-lg border border-dashed border-stone-500 bg-[#172018] p-4 text-sm text-stone-300">
          {recordings.length === 0 ? (
            <>
              No recordings have been published yet. See{' '}
              <a href="#/schedule" className="underline text-emerald-200">
                what&apos;s on the channels
              </a>{' '}
              — new meeting recordings appear here after they are published.
            </>
          ) : (
            'No recordings match this filter. Clear the search or facets to browse everything.'
          )}
        </p>
      )}

      {state === 'ready' && pageItems.length > 0 && (
        <>
          <p className="text-sm text-stone-400" role="status" aria-live="polite">
            {filtered.length} recording{filtered.length === 1 ? '' : 's'}
            {query || year || body || Object.keys(cf).length > 0 ? ' match this filter' : ' published'} / page {currentPage} of {pageCount}
          </p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {pageItems.map((asset) => (
              <RecordingCard key={asset.asset_id} asset={asset} />
            ))}
          </div>
          {pageCount > 1 && (
            <nav aria-label="Recording pages" className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={currentPage <= 1}
                onClick={() => goToPage(currentPage - 1)}
                className="min-h-11 rounded-md border border-stone-500/60 px-4 py-2 text-sm font-medium text-stone-100 hover:border-emerald-300/60 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:opacity-40"
              >
                Previous
              </button>
              {Array.from({ length: pageCount }, (_, index) => index + 1).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-current={value === currentPage ? 'page' : undefined}
                  onClick={() => goToPage(value)}
                  className={`min-h-11 min-w-11 rounded-md border px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-emerald-200 ${
                    value === currentPage
                      ? 'border-emerald-300/80 bg-emerald-300/10 text-emerald-100'
                      : 'border-stone-500/60 text-stone-100 hover:border-emerald-300/60'
                  }`}
                >
                  {value}
                </button>
              ))}
              <button
                type="button"
                disabled={currentPage >= pageCount}
                onClick={() => goToPage(currentPage + 1)}
                className="min-h-11 rounded-md border border-stone-500/60 px-4 py-2 text-sm font-medium text-stone-100 hover:border-emerald-300/60 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:opacity-40"
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  )
}
