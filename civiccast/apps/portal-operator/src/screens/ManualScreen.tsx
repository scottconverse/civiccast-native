import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router'
import { ApiError, getManual } from '../api/client'
import { manualLink } from './manual-link'
import type { ManualTocEntry } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function TocList({ entries, activeId }: { entries: ManualTocEntry[]; activeId: string | null }) {
  return (
    <ol className="m-0 grid gap-0.5 p-0 text-sm" style={{ listStyle: 'none' }}>
      {entries.map((entry) => (
        <li key={entry.id} style={{ paddingLeft: `${Math.max(0, entry.level - 1) * 0.85}rem` }}>
          {/* A real react-router Link (not a raw <a> + preventDefault): its
              `to` resolves correctly whether the app is mounted under
              BrowserRouter or HashRouter (the packaged operator console
              uses HashRouter at /operator/#/...), and native browser
              affordances -- middle-click/ctrl-click to open in a new tab,
              "Copy link" -- work exactly the way they do for any other
              in-app link. Clicking it changes location.hash, which the
              effect below reacts to. */}
          <Link
            to={manualLink(entry.id)}
            aria-current={activeId === entry.id ? 'location' : undefined}
            className="block truncate rounded-md px-2 py-1"
            style={{
              color: activeId === entry.id ? 'var(--cc-brand)' : 'var(--cc-ink-2)',
              background: activeId === entry.id ? 'var(--cc-brand-soft)' : 'transparent',
              fontWeight: entry.level <= 2 ? 600 : 400,
              fontSize: entry.level <= 1 ? '0.9rem' : '0.82rem',
            }}
          >
            {entry.title}
          </Link>
        </li>
      ))}
    </ol>
  )
}

export function ManualScreen() {
  const location = useLocation()
  const contentRef = useRef<HTMLDivElement | null>(null)
  const [filter, setFilter] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)
  const manualQuery = useQuery({
    queryKey: ['operator-manual'],
    queryFn: getManual,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const toc = manualQuery.data?.toc
  const filteredToc = useMemo(() => {
    const entries = toc ?? []
    const needle = filter.trim().toLowerCase()
    if (!needle) return entries
    return entries.filter((entry) => entry.title.toLowerCase().includes(needle))
  }, [toc, filter])

  // Deep-link support: /help#<section-id>, e.g. a "Read more in the manual"
  // link from a provider setup card, or a TocList click (which navigates
  // through react-router's own <Link>, changing location.hash -- never a
  // direct window.history call, which would rewrite the real browser URL
  // out from under HashRouter's own '/operator/#/...' scheme). Runs once
  // the manual HTML is actually in the DOM, since scrollIntoView needs the
  // target element to exist.
  useEffect(() => {
    if (!manualQuery.isSuccess) return
    const hash = location.hash.replace(/^#/, '')
    if (!hash) return undefined
    // getElementById (not a CSS-selector query) so this needs no CSS.escape
    // polyfill and works for any id pandoc's slugger produces. Let the
    // injected HTML paint first.
    const raf = window.requestAnimationFrame(() => {
      const target = contentRef.current && document.getElementById(hash)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        setActiveId(hash)
      }
    })
    return () => window.cancelAnimationFrame(raf)
  }, [manualQuery.isSuccess, location.hash])

  return (
    <div className="grid gap-4 px-6 py-5">
      <header className="max-w-3xl">
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Help
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Operator manual</h1>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          This is the same manual that ships as docs/USER-MANUAL.md, rendered here so it works
          with no internet connection. Signing in, getting a video in, packaging, publishing,
          where recordings live, and a plain-language glossary of provider jargon are all in
          here.
        </p>
      </header>

      {manualQuery.isLoading && (
        <div role="status" className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Loading the operator manual...
        </div>
      )}

      {manualQuery.error && (
        <div role="alert" className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          The manual could not load. {apiMessage(manualQuery.error, 'Try again.')}
        </div>
      )}

      {manualQuery.data && (
        <div className="grid gap-4 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)] lg:items-start">
          <nav
            aria-label="Manual contents"
            className="grid gap-2 rounded-md p-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <label className="grid gap-1 text-xs" htmlFor="manual-filter">
              <span className="sr-only">Filter manual sections</span>
              <input
                id="manual-filter"
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Search this manual"
                className="rounded-md px-3 py-2 text-sm"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            {filteredToc.length === 0 ? (
              <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                No section title matches &quot;{filter}&quot;.
              </p>
            ) : (
              <TocList entries={filteredToc} activeId={activeId} />
            )}
          </nav>

          <div
            ref={contentRef}
            className="cc-manual-prose rounded-md p-5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            // The HTML rendered here comes from civiccast/docsite/manual.json,
            // which the backend build pipeline already ran through an
            // allowlist sanitizer (civiccast/docsite/render.py::sanitize_html)
            // before it was committed -- see docs/docsite-sync.md. It is not
            // user input and is not sanitized again client-side.
            dangerouslySetInnerHTML={{ __html: manualQuery.data.html }}
          />
        </div>
      )}
    </div>
  )
}
