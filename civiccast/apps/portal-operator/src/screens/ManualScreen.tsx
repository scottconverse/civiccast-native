// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useHref, useLocation, useNavigate } from 'react-router'
import { ApiError, getManual } from '../api/client'
import { manualLink } from './manual-link'
import type { ManualTocEntry } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

type TocChapter = { entry: ManualTocEntry; sections: ManualTocEntry[] }
type TocPart = { entry: ManualTocEntry; chapters: TocChapter[]; sections: ManualTocEntry[] }

function groupContents(entries: ManualTocEntry[]) {
  const parts: TocPart[] = []
  const leading: ManualTocEntry[] = []
  const chapterForId = new Map<string, string>()
  let part: TocPart | undefined
  let chapter: TocChapter | undefined
  for (const entry of entries) {
    if (entry.level === 1) {
      part = { entry, chapters: [], sections: [] }
      parts.push(part)
      chapter = undefined
    } else if (entry.level === 2 && part) {
      chapter = { entry, sections: [] }
      part.chapters.push(chapter)
    } else if (chapter) {
      chapter.sections.push(entry)
    } else if (part) {
      part.sections.push(entry)
    } else {
      leading.push(entry)
    }
    if (chapter) chapterForId.set(entry.id, chapter.entry.id)
  }
  return { parts, leading, chapterForId }
}

function TocList({ entries, activeId }: { entries: ManualTocEntry[]; activeId: string | null }) {
  return (
    <ol className="m-0 grid gap-0.5 p-0 text-sm" style={{ listStyle: 'none' }}>
      {entries.map((entry) => (
        <li key={entry.id} style={{ paddingLeft: `${Math.min(2, Math.max(0, entry.level - 1)) * 0.6}rem`, minWidth: 0 }}>
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
            className="block rounded-md px-2 py-1"
            style={{
              color: activeId === entry.id ? 'var(--cc-brand)' : 'var(--cc-ink-2)',
              background: activeId === entry.id ? 'var(--cc-brand-soft)' : 'transparent',
              fontWeight: entry.level <= 2 ? 600 : 400,
              fontSize: entry.level <= 1 ? '0.9rem' : '0.82rem',
              overflowWrap: 'anywhere',
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
  const navigate = useNavigate()
  const manualHref = useHref('/help')
  const contentRef = useRef<HTMLDivElement | null>(null)
  const [filter, setFilter] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [expandedChapter, setExpandedChapter] = useState<string | null>(null)
  const manualQuery = useQuery({
    queryKey: ['operator-manual'],
    queryFn: getManual,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const toc = manualQuery.data?.toc
  const contents = useMemo(() => groupContents(toc ?? []), [toc])
  const bodyHtml = useMemo(() => {
    // Template content is inert. Transform only already-sanitized manual links,
    // preserving real router-aware hrefs for copy, middle-click and new tabs.
    const template = document.createElement('template')
    template.innerHTML = manualQuery.data?.html ?? ''
    for (const link of template.content.querySelectorAll('a[href]')) {
      const href = link.getAttribute('href') ?? ''
      if (href.startsWith('#') && href.length > 1) {
        link.setAttribute('href', `${manualHref}${href}`)
      } else if (/^https?:\/\//i.test(href)) {
        link.setAttribute('target', '_blank')
        link.setAttribute('rel', 'noopener noreferrer')
      }
    }
    for (const [index, table] of [...template.content.querySelectorAll('table')].entries()) {
      const region = document.createElement('div')
      region.className = 'cc-manual-table-scroll'
      region.setAttribute('role', 'region')
      region.setAttribute('aria-label', `Scrollable manual table ${index + 1}`)
      region.tabIndex = 0
      table.replaceWith(region)
      region.append(table)
    }
    return template.innerHTML
  }, [manualQuery.data?.html, manualHref])
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
  useLayoutEffect(() => {
    if (!manualQuery.isSuccess) return
    const hash = location.hash.replace(/^#/, '')
    // Commit the chapter layout before scrolling: on mobile the contents
    // sit above the body, so expanding them after scroll shifts the target.
    const target = hash && contentRef.current && document.getElementById(hash)
    const validTarget = target && contentRef.current?.contains(target)
    setActiveId(validTarget ? hash : null)
    setExpandedChapter(validTarget ? contents.chapterForId.get(hash) ?? null : null)
    // getElementById avoids CSS.escape assumptions for Pandoc IDs.
    const raf = window.requestAnimationFrame(() => {
      // State commits can replace the injected body; never scroll a detached
      // element captured before the expanded contents render.
      const paintedTarget = hash && document.getElementById(hash)
      if (paintedTarget && contentRef.current?.contains(paintedTarget)) {
        paintedTarget.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    })
    return () => window.cancelAnimationFrame(raf)
    // A new router entry may retain the same hash (a repeated section click).
    // Its key still changes, so every navigation action can scroll again.
  }, [manualQuery.isSuccess, location.hash, location.key, contents])

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 px-6 py-5">
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
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)] lg:items-start">
          <nav
            aria-label="Manual contents"
            className="grid min-w-0 gap-2 rounded-md p-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <label className="grid gap-1 text-xs" htmlFor="manual-filter">
              <span className="sr-only">Filter sections by title</span>
              <input
                id="manual-filter"
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter sections by title"
                className="rounded-md px-3 py-2 text-sm"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            {filteredToc.length === 0 ? (
              <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                No section title matches &quot;{filter}&quot;. Try one word, such as captions or backup.
              </p>
            ) : filter.trim() || contents.parts.length === 0 ? (
              <TocList entries={filteredToc} activeId={activeId} />
            ) : (
              <div className="grid gap-3">
                {contents.leading.length > 0 && <TocList entries={contents.leading} activeId={activeId} />}
                {contents.parts.map((part) => (
                  <section key={part.entry.id} aria-label={part.entry.title} className="min-w-0">
                    <TocList entries={[part.entry]} activeId={activeId} />
                    {part.sections.length > 0 && <TocList entries={part.sections} activeId={activeId} />}
                    {part.chapters.map((chapter) => {
                      const expanded = expandedChapter === chapter.entry.id
                      const panelId = `manual-contents-${chapter.entry.id}`
                      return (
                        <div key={chapter.entry.id} className="min-w-0">
                          <div className="flex items-start">
                            <div className="min-w-0 flex-1"><TocList entries={[chapter.entry]} activeId={activeId} /></div>
                            {chapter.sections.length > 0 && (
                              <button
                                type="button"
                                aria-label={`${expanded ? 'Hide' : 'Show'} sections for ${chapter.entry.title}`}
                                aria-expanded={expanded}
                                aria-controls={panelId}
                                onClick={() => setExpandedChapter(expanded ? null : chapter.entry.id)}
                                className="shrink-0 rounded-md px-2 py-1"
                                style={{ color: 'var(--cc-ink-2)', minWidth: 32, minHeight: 32 }}
                              >
                                <span aria-hidden="true">{expanded ? '−' : '+'}</span>
                              </button>
                            )}
                          </div>
                          {chapter.sections.length > 0 && (
                            <div id={panelId} hidden={!expanded}>
                              {expanded && <TocList entries={chapter.sections} activeId={activeId} />}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </section>
                ))}
              </div>
            )}
          </nav>

          <div
            ref={contentRef}
            onClick={(event) => {
              if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
              const link = event.target instanceof Element ? event.target.closest('a') : null
              if (!link || !event.currentTarget.contains(link) || link.hasAttribute('download') || (link.target && link.target !== '_self')) return
              const href = link.getAttribute('href') ?? ''
              const prefix = `${manualHref}#`
              if (!href.startsWith(prefix) || href.length === prefix.length) return
              event.preventDefault()
              navigate(manualLink(href.slice(prefix.length)))
            }}
            className="cc-manual-prose rounded-md p-5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            // The HTML rendered here comes from civiccast/docsite/manual.json,
            // which the backend build pipeline already ran through an
            // allowlist sanitizer (civiccast/docsite/render.py::sanitize_html)
            // before it was committed -- see docs/docsite-sync.md. It is not
            // user input and is not sanitized again client-side.
            dangerouslySetInnerHTML={{ __html: bodyHtml }}
          />
        </div>
      )}
    </div>
  )
}
