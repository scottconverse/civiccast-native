import { useEffect, type RefObject } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'summary:not([aria-disabled="true"])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function isHiddenByClosedDetails(element: HTMLElement): boolean {
  let closedDetails = element.closest<HTMLDetailsElement>('details:not([open])')
  while (closedDetails) {
    const summary = Array.from(closedDetails.children).find(
      (child) => child.tagName === 'SUMMARY',
    )
    if (summary !== element) return true
    closedDetails = closedDetails.parentElement?.closest<HTMLDetailsElement>(
      'details:not([open])',
    ) ?? null
  }
  return false
}

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) =>
      !element.hasAttribute('disabled') &&
      element.getAttribute('aria-hidden') !== 'true' &&
      !isHiddenByClosedDetails(element) &&
      element.offsetParent !== null,
  )
}

export function useFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const first = focusableElements(root)[0] ?? root
    first.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const focusable = focusableElements(root)
      if (focusable.length === 0) {
        event.preventDefault()
        root.focus()
        return
      }
      const firstElement = focusable[0]
      const lastElement = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey && active === firstElement) {
        event.preventDefault()
        lastElement.focus()
        return
      }
      if (!event.shiftKey && active === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previous?.focus()
    }
  }, [ref])
}
