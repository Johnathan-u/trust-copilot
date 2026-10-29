import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { presentHttpFailure } from '@/lib/api-error'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PartialSuccess } from '@/components/ui/PartialSuccess'
import { TakingLonger } from '@/components/ui/TakingLonger'
import { RETRY_LABEL } from '@/lib/ui-state'

describe('state primitives markup', () => {
  it('renders a loading region that is not an empty result', () => {
    const html = renderToStaticMarkup(
      createElement(LoadingState, {
        label: 'Loading dashboard',
        onRetry: () => {},
        children: createElement('div', { 'data-skeleton': 'true' }, 'skeleton'),
      })
    )
    expect(html).toContain('data-state="loading"')
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('Loading dashboard')
    expect(html).toContain('data-skeleton="true"')
    expect(html).not.toContain('No shortcuts yet')
  })

  it('renders the slow state with a retry button', () => {
    const html = renderToStaticMarkup(
      createElement(TakingLonger, { onRetry: () => {}, label: 'Loading' })
    )
    expect(html).toContain('data-state="slow"')
    expect(html).toContain('role="status"')
    expect(html).toContain('This is taking longer than usual')
    expect(html).toContain(RETRY_LABEL)
    expect(html).toContain('Still loading')
  })

  it('renders distinct error alerts for 403, 404, 500, and offline', () => {
    for (const input of [
      { status: 403 },
      { status: 404 },
      { status: 500 },
      { offline: true },
    ]) {
      const failure = presentHttpFailure(input)
      const html = renderToStaticMarkup(
        createElement(ErrorState, { failure, onRetry: () => {} })
      )
      expect(html).toContain('role="alert"')
      expect(html).toContain(`data-failure="${failure.kind}"`)
      expect(html).toContain(failure.title)
      expect(html).toContain(RETRY_LABEL)
      expect(html.toLowerCase()).not.toContain('permission')
    }
  })

  it('renders an empty state with its action', () => {
    const html = renderToStaticMarkup(
      createElement(EmptyState, {
        title: 'No shortcuts yet',
        description: 'Nothing is listed.',
        titleAs: 'h2',
        action: createElement('button', { type: 'button' }, 'Open documents'),
      })
    )
    expect(html).toContain('data-state="empty"')
    expect(html).toContain('No shortcuts yet')
    expect(html).toContain('Open documents')
    expect(html).not.toContain('role="alert"')
  })

  it('renders partial success around the sections that loaded', () => {
    const html = renderToStaticMarkup(
      createElement(
        PartialSuccess,
        {
          failed: [
            {
              id: 'alerts',
              label: 'Security notices',
              failure: presentHttpFailure({ status: 500 }),
            },
          ],
          onRetry: () => {},
        },
        createElement('p', null, 'Synthetic card 1')
      )
    )
    expect(html).toContain('data-state="partial"')
    expect(html).toContain('role="alert"')
    expect(html.replaceAll('&#x27;', "'")).toContain(
      "Some sections didn't load"
    )
    expect(html).toContain('Try again: Security notices')
    expect(html).toContain('Synthetic card 1')
  })
})
