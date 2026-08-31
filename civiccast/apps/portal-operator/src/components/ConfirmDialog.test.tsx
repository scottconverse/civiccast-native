import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import { ConfirmDialog } from './ConfirmDialog'
import { feedCommandConfirmCopy } from '../screens/feed-command-confirm'

afterEach(cleanup)

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  const utils = render(
    <ConfirmDialog
      title="Stop the outgoing feed for Public Channel?"
      body="Residents watching lose the stream until the feed is started again."
      confirmLabel="Stop feed"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  )
  return { ...utils, onConfirm, onCancel }
}

describe('ConfirmDialog', () => {
  it('is an alertdialog labelled by the title and described by the consequence', () => {
    const { getByRole } = renderDialog()
    const dialog = getByRole('alertdialog')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.textContent).toContain('Stop the outgoing feed for Public Channel?')
    expect(dialog.textContent).toContain('Residents watching lose the stream')
  })

  it('moves initial focus to Cancel (the safe default)', () => {
    const { getByRole } = renderDialog()
    expect(document.activeElement).toBe(getByRole('button', { name: 'Cancel' }))
  })

  it('fires onConfirm only from the confirm button', () => {
    const { getByRole, onConfirm, onCancel } = renderDialog()
    expect(onConfirm).not.toHaveBeenCalled()
    fireEvent.click(getByRole('button', { name: 'Stop feed' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('cancels on the Cancel button, on Escape, and on a backdrop click', () => {
    const first = renderDialog()
    fireEvent.click(first.getByRole('button', { name: 'Cancel' }))
    expect(first.onCancel).toHaveBeenCalledTimes(1)
    expect(first.onConfirm).not.toHaveBeenCalled()
    cleanup()

    const second = renderDialog()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(second.onCancel).toHaveBeenCalledTimes(1)
    cleanup()

    const third = renderDialog()
    fireEvent.mouseDown(third.getByRole('alertdialog').parentElement as HTMLElement)
    expect(third.onCancel).toHaveBeenCalledTimes(1)
  })

  it('traps Tab focus inside the dialog in both directions', () => {
    const { getByRole } = renderDialog()
    const cancel = getByRole('button', { name: 'Cancel' })
    const confirm = getByRole('button', { name: 'Stop feed' })

    // Tab from the last focusable wraps to the first.
    confirm.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement).toBe(cancel)

    // Shift+Tab from the first wraps to the last.
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirm)
  })

  it('disables both buttons while busy', () => {
    const { getByRole } = renderDialog({ busy: true })
    expect((getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true)
    expect((getByRole('button', { name: 'Stop feed' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('restores focus to the opener when it closes', () => {
    const opener = document.createElement('button')
    opener.textContent = 'open'
    document.body.appendChild(opener)
    opener.focus()
    const { unmount } = renderDialog()
    expect(document.activeElement).not.toBe(opener)
    unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})

describe('feedCommandConfirmCopy', () => {
  it('names the channel and the resident-facing consequence for every command', () => {
    const stop = feedCommandConfirmCopy('stop', 'Public Channel')
    expect(stop.title).toBe('Stop the outgoing feed for Public Channel?')
    expect(stop.body).toContain('off the air')
    expect(stop.confirmLabel).toBe('Stop feed')

    expect(feedCommandConfirmCopy('start', 'Public Channel').confirmLabel).toBe('Start feed')
    expect(feedCommandConfirmCopy('reload', 'Public Channel').body).toContain('drops briefly')
    expect(feedCommandConfirmCopy('drain', 'Public Channel').confirmLabel).toBe(
      'Finish, then stop',
    )
  })
})
