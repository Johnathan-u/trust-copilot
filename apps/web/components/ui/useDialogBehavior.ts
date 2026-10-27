'use client'

import { useEffect, useRef, type RefObject } from 'react'
import { dialogAttributes, nextTabbableIndex, type DialogRole } from '@/lib/dialog'

const TABBABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'summary',
  '[contenteditable="true"]',
  '[tabindex]',
].join(',')

function isHidden(el: HTMLElement): boolean {
  if (el.closest('[hidden]')) return true
  const style = window.getComputedStyle(el)
  return style.display === 'none' || style.visibility === 'hidden'
}

export function listTabbables(container: HTMLElement): HTMLElement[] {
  const nodes = Array.from(container.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR))
  const seen = new Set<HTMLElement>()
  const result: HTMLElement[] = []
  for (const el of nodes) {
    if (seen.has(el)) continue
    seen.add(el)
    if (el.hasAttribute('disabled')) continue
    if (el.getAttribute('aria-disabled') === 'true') continue
    if (el.tabIndex < 0) continue
    if (isHidden(el)) continue
    result.push(el)
  }
  return result
}

function resolveInitialFocus(dialog: HTMLElement, explicit: HTMLElement | null, role: DialogRole): HTMLElement {
  if (explicit && dialog.contains(explicit)) return explicit
  if (role === 'alertdialog') {
    const dismiss = dialog.querySelector<HTMLElement>(
      `[${dialogAttributes.initial}="${dialogAttributes.initialDismiss}"]`
    )
    if (dismiss && !dismiss.hasAttribute('disabled')) return dismiss
  }
  const tabbables = listTabbables(dialog)
  const preferred = tabbables.find((el) => !el.hasAttribute(dialogAttributes.close))
  return preferred ?? tabbables[0] ?? dialog
}

function inertOutside(boundary: HTMLElement): HTMLElement[] {
  const changed: HTMLElement[] = []
  let current: HTMLElement | null = boundary
  while (current && current !== document.body) {
    const parent = current.parentElement
    if (!parent) break
    for (const sibling of Array.from(parent.children)) {
      if (!(sibling instanceof HTMLElement) || sibling === current) continue
      if (sibling.hasAttribute('inert')) continue
      if (sibling.getAttribute('aria-hidden') === 'true') continue
      sibling.setAttribute('inert', '')
      sibling.setAttribute('aria-hidden', 'true')
      sibling.setAttribute('data-tc-inert-applied', '')
      changed.push(sibling)
    }
    current = parent
  }
  return changed
}

function restoreInert(elements: HTMLElement[]) {
  for (const el of elements) {
    if (!el.hasAttribute('data-tc-inert-applied')) continue
    el.removeAttribute('inert')
    el.removeAttribute('aria-hidden')
    el.removeAttribute('data-tc-inert-applied')
  }
}

export function useDialogBehavior({
  open,
  onClose,
  dialogRef,
  boundaryRef,
  initialFocusRef,
  returnFocusRef,
  role = 'dialog',
  closeOnEscape = true,
  lockScroll = true,
}: {
  open: boolean
  onClose: () => void
  dialogRef: RefObject<HTMLElement | null>
  boundaryRef?: RefObject<HTMLElement | null>
  initialFocusRef?: RefObject<HTMLElement | null>
  returnFocusRef?: RefObject<HTMLElement | null>
  role?: DialogRole
  closeOnEscape?: boolean
  lockScroll?: boolean
}) {
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const roleRef = useRef(role)
  roleRef.current = role

  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const boundary = boundaryRef?.current ?? dialog

    const previous =
      document.activeElement instanceof HTMLElement && !dialog.contains(document.activeElement)
        ? document.activeElement
        : null
    const explicitReturn = returnFocusRef?.current ?? null

    const inerted = inertOutside(boundary)
    const previousOverflow = document.body.style.overflow
    if (lockScroll) document.body.style.overflow = 'hidden'

    const focusInitial = () => {
      const node = dialogRef.current
      if (!node) return
      const target = resolveInitialFocus(node, initialFocusRef?.current ?? null, roleRef.current)
      target.focus()
    }
    focusInitial()

    const onKeyDown = (event: KeyboardEvent) => {
      const node = dialogRef.current
      if (!node) return
      if (event.key === 'Escape') {
        if (!closeOnEscape) return
        event.preventDefault()
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const tabbables = listTabbables(node)
      if (tabbables.length === 0) {
        event.preventDefault()
        node.focus()
        return
      }
      const active = document.activeElement
      const index = active instanceof HTMLElement ? tabbables.indexOf(active) : -1
      if (tabbables.length === 1 || index === -1) {
        event.preventDefault()
        const edge = event.shiftKey ? tabbables[tabbables.length - 1] : tabbables[0]
        ;(index === -1 ? edge : tabbables[0]).focus()
        return
      }
      const atStart = index === 0
      const atEnd = index === tabbables.length - 1
      if ((event.shiftKey && atStart) || (!event.shiftKey && atEnd)) {
        event.preventDefault()
        tabbables[nextTabbableIndex(index, tabbables.length, event.shiftKey)].focus()
      }
    }

    const onFocusIn = (event: FocusEvent) => {
      const node = dialogRef.current
      if (!node) return
      const target = event.target
      if (target instanceof Node && node.contains(target)) return
      const tabbables = listTabbables(node)
      ;(tabbables[0] ?? node).focus()
    }

    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.removeEventListener('focusin', onFocusIn)
      restoreInert(inerted)
      if (lockScroll) document.body.style.overflow = previousOverflow
      const back = explicitReturn && document.contains(explicitReturn) ? explicitReturn : previous
      if (back && document.contains(back)) back.focus()
    }
  }, [open, closeOnEscape, lockScroll, dialogRef, boundaryRef, initialFocusRef, returnFocusRef])
}
