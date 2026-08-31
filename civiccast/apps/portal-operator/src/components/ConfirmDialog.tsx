// Shared confirmation dialog for destructive / on-air-affecting operator
// actions. One-click live buttons (stop a channel feed, wipe config, publish
// to residents) each open this dialog first; the copy names the concrete
// consequence in plain words, matching the console's existing two-step
// patterns (Commit-to-Air's "Take off air" flow, Paywall's arm→confirm).
//
// Accessibility contract (WCAG 2.2 AA):
// - role="alertdialog" + aria-modal, labelled by the title, described by the
//   body, so screen readers announce the consequence before the choice.
// - Focus moves to the Cancel button on open (safe default), Tab/Shift+Tab
//   are trapped inside the dialog, Escape cancels, and focus returns to the
//   element that opened the dialog on close.
// - Clicking the backdrop cancels; nothing outside is reachable while open.
//
// Deliberately NOT used for safe/read-only actions (checks, previews,
// refreshes) — confirmation fatigue is its own bug.

import { useEffect, useRef } from 'react'

export interface ConfirmDialogProps {
  /** Short question naming the action, e.g. "Stop the feed for Channel 1?" */
  title: string
  /** Plain-words consequence, e.g. "Residents lose the stream until it is started again." */
  body: string
  /** Verb-first confirm label, e.g. "Stop feed" — never a bare "OK". */
  confirmLabel: string
  cancelLabel?: string
  /** "danger" paints the confirm button in the error tone; "brand" keeps the ink tone. */
  tone?: 'danger' | 'brand'
  /** Disables both buttons while the confirmed mutation is in flight. */
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = 'Cancel',
  tone = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const cancelRef = useRef<HTMLButtonElement | null>(null)
  const onCancelRef = useRef(onCancel)
  useEffect(() => {
    onCancelRef.current = onCancel
  }, [onCancel])

  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    cancelRef.current?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCancelRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const root = dialogRef.current
      if (!root) return
      const focusables = Array.from(
        root.querySelectorAll<HTMLElement>('button:not([disabled])'),
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement
      if (event.shiftKey) {
        if (active === first || !root.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !root.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }
    // Capture phase so screens with their own global key handlers (e.g. the
    // trim editor) never see keystrokes while the dialog is open.
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      previouslyFocused?.focus()
    }
  }, [])

  const confirmBg = tone === 'danger' ? 'var(--cc-err)' : 'var(--cc-ink)'
  const confirmFg = tone === 'danger' ? 'white' : 'var(--cc-ink-inv)'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'color-mix(in srgb, var(--cc-ink) 45%, transparent)' }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-body"
        className="grid w-full max-w-md gap-3 rounded-md p-5"
        style={{
          background: 'var(--cc-surface)',
          border: '1px solid var(--cc-line)',
          boxShadow: '0 12px 32px rgba(0, 0, 0, 0.35)',
        }}
      >
        <h2 id="confirm-dialog-title" className="m-0 text-base font-semibold">
          {title}
        </h2>
        <p id="confirm-dialog-body" className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          {body}
        </p>
        <div className="mt-1 flex flex-wrap justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            disabled={busy}
            onClick={onCancel}
            className="rounded-md px-3 py-2 text-sm font-medium"
            style={{
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink-2)',
              background: 'var(--cc-surface)',
            }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: busy ? 'var(--cc-surface-3)' : confirmBg,
              color: busy ? 'var(--cc-ink-3)' : confirmFg,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * The confirmation request a screen stages before running a destructive
 * action: the dialog copy plus the action to run on confirm. Screens keep
 * `useState<PendingConfirm | null>` and render one <ConfirmDialog> from it.
 */
export interface PendingConfirm {
  title: string
  body: string
  confirmLabel: string
  tone?: 'danger' | 'brand'
  run: () => void
}
