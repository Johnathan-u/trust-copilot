'use client'

import { useEffect, useRef, type RefObject } from 'react'
import {
  chooseReturnFocus,
  dialogAttributes,
  nextTabbableIndex,
  type DialogRole,
} from '@/lib/dialog'
import {
  isPersistentToastLiveHost,
  persistentToastRegions,
  TOAST_LIVE_ROOT_ID,
} from '@/lib/toast'

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
  const nodes = Array.from(
    container.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)
  )
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

function resolveInitialFocus(
  dialog: HTMLElement,
  explicit: HTMLElement | null,
  role: DialogRole
): HTMLElement {
  if (explicit && dialog.contains(explicit)) return explicit
  if (role === 'alertdialog') {
    const dismiss = dialog.querySelector<HTMLElement>(
      `[${dialogAttributes.initial}="${dialogAttributes.initialDismiss}"]`
    )
    if (dismiss && !dismiss.hasAttribute('disabled')) return dismiss
  }
  const tabbables = listTabbables(dialog)
  const preferred = tabbables.find(
    (el) => !el.hasAttribute(dialogAttributes.close)
  )
  return preferred ?? tabbables[0] ?? dialog
}

function hostsPersistentToastRegion(el: HTMLElement): boolean {
  if (isPersistentToastLiveHost(el.id)) return true
  if (el.querySelector(`#${TOAST_LIVE_ROOT_ID}`)) return true
  return persistentToastRegions().some((region) =>
    Boolean(el.querySelector(`#${region.id}`))
  )
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
      if (hostsPersistentToastRegion(sibling)) continue
      sibling.setAttribute('inert', '')
      sibling.setAttribute('aria-hidden', 'true')
      sibling.setAttribute('data-tc-inert-applied', '')
      changed.push(sibling)
    }
    current = parent
  }
  return changed
}

function canTakeReturnFocus(el: HTMLElement): boolean {
  if (!document.contains(el)) return false
  if (el.hasAttribute('disabled')) return false
  if (el.getAttribute('aria-disabled') === 'true') return false
  if (el.closest('[inert]')) return false
  if (isHidden(el)) return false
  const rect = el.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0
}

function returnFocusFallbacks(): HTMLElement[] {
  const found: HTMLElement[] = []
  const main = document.getElementById('main-content')
  if (main instanceof HTMLElement) found.push(main)
  const dockLink = document.querySelector(
    '[data-sidebar-placement="dock"] a[href]'
  )
  if (dockLink instanceof HTMLElement) found.push(dockLink)
  return found
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
  const roleRef = useRef(role)
  useEffect(() => {
    onCloseRef.current = onClose
    roleRef.current = role
  }, [onClose, role])

  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const boundary = boundaryRef?.current ?? dialog

    const previous =
      document.activeElement instanceof HTMLElement &&
      !dialog.contains(document.activeElement)
        ? document.activeElement
        : null
    const explicitReturn = returnFocusRef?.current ?? null

    const inerted = inertOutside(boundary)
    const previousOverflow = document.body.style.overflow
    if (lockScroll) document.body.style.overflow = 'hidden'

    const focusInitial = () => {
      const node = dialogRef.current
      if (!node) return
      const target = resolveInitialFocus(
        node,
        initialFocusRef?.current ?? null,
        roleRef.current
      )
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
      const index =
        active instanceof HTMLElement ? tabbables.indexOf(active) : -1
      if (tabbables.length === 1 || index === -1) {
        event.preventDefault()
        const edge = event.shiftKey
          ? tabbables[tabbables.length - 1]
          : tabbables[0]
        ;(index === -1 ? edge : tabbables[0]).focus()
        return
      }
      const atStart = index === 0
      const atEnd = index === tabbables.length - 1
      if ((event.shiftKey && atStart) || (!event.shiftKey && atEnd)) {
        event.preventDefault()
        tabbables[
          nextTabbableIndex(index, tabbables.length, event.shiftKey)
        ].focus()
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
      const ordered: HTMLElement[] = []
      const push = (el: HTMLElement | null) => {
        if (!el || ordered.includes(el) || !document.contains(el)) return
        ordered.push(el)
      }
      push(explicitReturn)
      push(previous)
      for (const fallback of returnFocusFallbacks()) push(fallback)
      const chosen = chooseReturnFocus(
        ordered.map((el) => {
          const available = canTakeReturnFocus(el)
          return { el, visible: available, focusable: available }
        })
      )
      chosen?.el.focus()
    }
  }, [
    open,
    closeOnEscape,
    lockScroll,
    dialogRef,
    boundaryRef,
    initialFocusRef,
    returnFocusRef,
  ])
}
