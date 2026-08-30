// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S7 / candidate #17 field evidence, finding 3: "auto-ingest requires you to
// create a folder on disk, know and paste its exact path... NO 'Browse...'
// picker." A browser cannot hand back an absolute filesystem path itself
// (the File System Access API and `<input webkitdirectory>` both withhold
// it for security) -- but this app's frontend and backend always run on the
// SAME station machine, so `GET /api/staff/media-lifecycle/browse-folders`
// lists local directories for this picker to navigate instead of asking a
// non-technical operator to type one from memory.

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, browseFolders } from '../../api/client'
import { useFocusTrap } from '../../hooks/useFocusTrap'

export interface FolderBrowserProps {
  /** Pre-populate navigation at this path when it looks like a real, absolute path. */
  initialPath?: string
  onSelect: (path: string) => void
  onClose: () => void
}

function looksLikeAbsolutePath(value: string): boolean {
  return /^([A-Za-z]:\\|\\\\|\/)/.test(value.trim())
}

export function FolderBrowser({ initialPath, onSelect, onClose }: FolderBrowserProps) {
  const [currentPath, setCurrentPath] = useState<string | null>(
    initialPath && looksLikeAbsolutePath(initialPath) ? initialPath : null,
  )
  const sheetRef = useRef<HTMLDivElement>(null)
  useFocusTrap(sheetRef)
  const headingId = 'folder-browser-heading'

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const query = useQuery({
    queryKey: ['folder-browse', currentPath],
    queryFn: () => browseFolders(currentPath ?? undefined),
    retry: false,
  })

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <button
        type="button"
        aria-label="Close folder browser backdrop"
        onClick={onClose}
        className="absolute inset-0"
        style={{ background: 'transparent' }}
      />
      <div
        ref={sheetRef}
        className="relative grid w-full max-w-lg gap-3 rounded-md p-4"
        style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', maxHeight: '80vh' }}
      >
        <div className="flex items-start justify-between gap-2">
          <h2 id={headingId} className="m-0 text-base font-semibold">
            Choose a folder
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-xs"
            style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)' }}
          >
            Cancel
          </button>
        </div>

        <div
          className="cc-mono flex items-center justify-between gap-2 rounded-md px-3 py-2 text-xs"
          style={{ background: 'var(--cc-surface-2)' }}
        >
          <span className="cc-truncate">{currentPath ?? 'Drives'}</span>
          {currentPath != null && (
            <button
              type="button"
              onClick={() => setCurrentPath(query.data?.parent_path ?? null)}
              className="shrink-0 rounded-md px-2 py-1 text-[11px] font-medium"
              style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
            >
              Up
            </button>
          )}
        </div>

        {query.isLoading && (
          <div className="h-24 w-full animate-pulse rounded-md" style={{ background: 'var(--cc-surface-2)' }} />
        )}
        {query.isError && (
          <p role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
            {query.error instanceof ApiError && query.error.detail
              ? query.error.detail
              : 'Could not list folders.'}
          </p>
        )}
        {query.isSuccess && !query.data.readable && (
          <p role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
            Can&apos;t open this folder{query.data.error ? `: ${query.data.error}` : '.'}
          </p>
        )}
        {query.isSuccess && query.data.readable && (
          <ul
            className="flex max-h-64 flex-col gap-1 overflow-y-auto"
            aria-label="Folders"
          >
            {query.data.entries.length === 0 && (
              <li className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                No subfolders here.
              </li>
            )}
            {query.data.entries.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  onClick={() => setCurrentPath(entry.path)}
                  className="w-full rounded-md px-3 py-2 text-left text-sm"
                  style={{ border: '1px solid var(--cc-line)', background: 'var(--cc-surface)' }}
                >
                  📁 {entry.name}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex justify-end gap-2 border-t pt-3" style={{ borderColor: 'var(--cc-line)' }}>
          <button
            type="button"
            disabled={currentPath == null}
            onClick={() => currentPath != null && onSelect(currentPath)}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: currentPath == null ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: currentPath == null ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            Use this folder
          </button>
        </div>
      </div>
    </div>
  )
}
