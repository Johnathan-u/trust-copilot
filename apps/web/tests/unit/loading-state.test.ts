// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LoadingState } from '@/components/ui/LoadingState'
import {
  RETRY_LABEL,
  SKELETON_TIMEOUT_MS,
  SLOW_LOADING_COPY,
} from '@/lib/ui-state'

const LABEL = 'Loading records'

function renderLoading() {
  return render(
    createElement(
      LoadingState,
      { label: LABEL, onRetry: () => {} },
      createElement('div', null, 'placeholder rows')
    )
  )
}

describe('LoadingState slow-load switch', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('keeps the loading content until 8s, then shows the slow message', () => {
    expect(SKELETON_TIMEOUT_MS).toBe(8000)
    renderLoading()

    expect(screen.getByText('placeholder rows')).toBeTruthy()
    expect(screen.getByText(LABEL)).toBeTruthy()
    expect(document.querySelector('[data-state="loading"]')).toBeTruthy()
    expect(screen.queryByText(SLOW_LOADING_COPY.title)).toBeNull()

    act(() => {
      vi.advanceTimersByTime(7999)
    })

    expect(screen.getByText('placeholder rows')).toBeTruthy()
    expect(screen.getByText(LABEL)).toBeTruthy()
    expect(document.querySelector('[data-state="loading"]')).toBeTruthy()
    expect(screen.queryByText(SLOW_LOADING_COPY.title)).toBeNull()
    expect(screen.queryByRole('button', { name: RETRY_LABEL })).toBeNull()

    act(() => {
      vi.advanceTimersByTime(1)
    })

    expect(screen.getByText(SLOW_LOADING_COPY.title)).toBeTruthy()
    expect(screen.getByRole('button', { name: RETRY_LABEL })).toBeTruthy()
    expect(document.querySelector('[data-state="slow"]')).toBeTruthy()
    expect(screen.queryByText('placeholder rows')).toBeNull()
    expect(document.querySelector('[data-state="loading"]')).toBeNull()
  })

  it('clears the timer on unmount and does not update after that', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { unmount } = renderLoading()

    act(() => {
      vi.advanceTimersByTime(7999)
    })
    expect(screen.getByText('placeholder rows')).toBeTruthy()
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    unmount()
    expect(vi.getTimerCount()).toBe(0)

    error.mockClear()
    warn.mockClear()
    act(() => {
      vi.advanceTimersByTime(SKELETON_TIMEOUT_MS)
    })

    expect(error).not.toHaveBeenCalled()
    expect(warn).not.toHaveBeenCalled()
    expect(document.body.textContent ?? '').not.toContain(
      SLOW_LOADING_COPY.title
    )
    expect(document.querySelector('[data-state="slow"]')).toBeNull()
  })
})
