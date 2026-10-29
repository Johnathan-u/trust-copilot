import { describe, expect, it } from 'vitest'

import {
  INVALID_ANSWER_ID_MESSAGE,
  MISSING_VENDOR_TOKEN_MESSAGE,
  MISSING_VERIFICATION_MESSAGE,
  cardFormDraft,
  cardFormInputsChanged,
  caseStudyQuoteFields,
  clampIndex,
  gatedLoadFlags,
  inactiveSearch,
  listLoadFlags,
  navOpenForPath,
  nextGeneration,
  nextPaletteIndex,
  pageAfterFilterChange,
  proofChainRequest,
  shouldClearCitationTags,
  shouldResetCaseStudyFields,
  slowLoadingAfterChange,
  subscribeToastRegion,
  toastPortalTarget,
  trustLandingPath,
  vendorRequestWithoutToken,
  verificationWithoutToken,
  wholeSecondsBetween,
} from '@/lib/render-state'

describe('keyed generation', () => {
  it('counts each new key once and ignores a repeat', () => {
    const first = nextGeneration(null, 'a', 0)
    const repeat = nextGeneration(first.key, 'a', first.generation)
    const second = nextGeneration(repeat.key, 'b', repeat.generation)
    expect(first).toEqual({ key: 'a', generation: 1, changed: true })
    expect(repeat.changed).toBe(false)
    expect(repeat.generation).toBe(1)
    expect(second).toEqual({ key: 'b', generation: 2, changed: true })
  })
})

describe('section loading flags', () => {
  it('turns loading off when the viewer is not allowed to fetch', () => {
    expect(gatedLoadFlags(false)).toEqual({
      loading: false,
      clearFailure: false,
    })
    expect(gatedLoadFlags(true)).toEqual({ loading: true, clearFailure: true })
  })

  it('keeps existing rows visible while a new query runs', () => {
    expect(listLoadFlags({ enabled: false, hasRows: true })).toEqual({
      loading: false,
      refreshing: false,
      clearFailure: false,
    })
    expect(listLoadFlags({ enabled: true, hasRows: false })).toEqual({
      loading: true,
      refreshing: true,
      clearFailure: true,
    })
    expect(listLoadFlags({ enabled: true, hasRows: true }).loading).toBeNull()
  })
})

describe('resets that follow an input change', () => {
  it('returns to page 1 only after the filter query changes', () => {
    expect(pageAfterFilterChange(null, 'all|168', 4)).toBe(4)
    expect(pageAfterFilterChange('all|168', 'all|168', 4)).toBe(4)
    expect(pageAfterFilterChange('all|168', 'auth|168', 4)).toBe(1)
  })

  it('resets the palette highlight when it opens and clamps it to the list', () => {
    expect(clampIndex(3, 0)).toBe(0)
    expect(clampIndex(-1, 4)).toBe(0)
    expect(clampIndex(9, 4)).toBe(3)
    expect(
      nextPaletteIndex({
        open: true,
        previouslyOpen: false,
        index: 3,
        count: 2,
        countChanged: false,
      })
    ).toBe(0)
    expect(
      nextPaletteIndex({
        open: true,
        previouslyOpen: true,
        index: 5,
        count: 3,
        countChanged: true,
      })
    ).toBe(2)
    expect(
      nextPaletteIndex({
        open: false,
        previouslyOpen: true,
        index: 2,
        count: 4,
        countChanged: false,
      })
    ).toBe(2)
  })

  it('closes the nav drawer when the path changes and not on the first path', () => {
    expect(navOpenForPath(null, '/dashboard', true)).toBe(true)
    expect(navOpenForPath('/dashboard', '/dashboard', true)).toBe(true)
    expect(navOpenForPath('/dashboard', '/dashboard/audit', true)).toBe(false)
  })

  it('clears citation tags only when the drawer closes', () => {
    expect(shouldClearCitationTags(false, true)).toBe(false)
    expect(shouldClearCitationTags(true, true)).toBe(false)
    expect(shouldClearCitationTags(true, false)).toBe(true)
  })

  it('restarts the slow-loading flag when an active timer key changes', () => {
    expect(slowLoadingAfterChange(true, true, true)).toBe(false)
    expect(slowLoadingAfterChange(false, true, true)).toBe(true)
    expect(slowLoadingAfterChange(true, false, true)).toBe(true)
  })
})

describe('derived views', () => {
  it('treats a short query or a missing workspace as no search', () => {
    expect(inactiveSearch(' a ', 4)).toBe(true)
    expect(inactiveSearch('abc', null)).toBe(true)
    expect(inactiveSearch('abc', undefined)).toBe(true)
    expect(inactiveSearch('  ab ', 4)).toBe(false)
  })

  it('redirects the trust landing page only when a default slug is configured', () => {
    expect(trustLandingPath('')).toBeNull()
    expect(trustLandingPath('acme')).toBe('/trust/acme')
  })

  it('describes a missing verification or vendor token without a request', () => {
    expect(verificationWithoutToken(null)).toEqual({
      status: 'error',
      message: MISSING_VERIFICATION_MESSAGE,
    })
    expect(verificationWithoutToken('tok')).toEqual({
      status: 'loading',
      message: '',
    })
    expect(vendorRequestWithoutToken(null)).toEqual({
      loading: false,
      error: MISSING_VENDOR_TOKEN_MESSAGE,
    })
    expect(vendorRequestWithoutToken('tok').loading).toBe(true)
  })

  it('rejects a proof-chain id that is not a positive integer', () => {
    expect(proofChainRequest('')).toEqual({
      error: INVALID_ANSWER_ID_MESSAGE,
    })
    expect(proofChainRequest('0').error).toBe(INVALID_ANSWER_ID_MESSAGE)
    expect(proofChainRequest('12')).toEqual({ id: 12 })
    expect(proofChainRequest('12abc')).toEqual({ id: 12 })
  })

  it('copies card and case-study fields when their source changes', () => {
    expect(cardFormDraft(null, '/dashboard/documents').targetRoute).toBe(
      '/dashboard/documents'
    )
    expect(
      cardFormDraft(
        {
          title: 'Evidence',
          description: null,
          icon: 'shield',
          target_route: '/dashboard/documents',
          visibility_scope: null,
          size: null,
          is_enabled: false,
        },
        '/dashboard'
      )
    ).toEqual({
      title: 'Evidence',
      description: '',
      icon: 'shield',
      targetRoute: '/dashboard/documents',
      visibility: 'all',
      size: 'medium',
      enabled: false,
    })
    const card = { id: 1 }
    const meta = { routes: ['/dashboard'] }
    expect(
      cardFormInputsChanged(null, { card, allowedMeta: meta, isOpen: false })
    ).toBe(true)
    expect(
      cardFormInputsChanged(
        { card, allowedMeta: meta, isOpen: false },
        { card, allowedMeta: meta, isOpen: true }
      )
    ).toBe(true)
    const study = { company_name: 'Acme', quoted_results: ['faster reviews'] }
    expect(caseStudyQuoteFields(study)).toEqual({
      organizationName: 'Acme',
      resultKey: 'faster reviews',
    })
    expect(
      caseStudyQuoteFields({ company_name: null, quoted_results: [] })
    ).toEqual({
      organizationName: '',
      resultKey: '',
    })
    const seen = {
      id: 1,
      companyName: 'Acme',
      quotedResults: study.quoted_results,
    }
    expect(shouldResetCaseStudyFields(seen, seen)).toBe(false)
    expect(shouldResetCaseStudyFields(seen, { ...seen, id: 2 })).toBe(true)
  })

  it('formats elapsed whole seconds and keeps the toast region off the server', () => {
    expect(wholeSecondsBetween(2500, 0)).toBe(2)
    expect(wholeSecondsBetween(100, 500)).toBe(0)
    expect(wholeSecondsBetween(Number.NaN, 0)).toBe(0)
    const element = { id: 'region' } as HTMLElement
    expect(toastPortalTarget(true, element)).toBeNull()
    expect(toastPortalTarget(false, element)).toBe(element)
    expect(typeof subscribeToastRegion()).toBe('function')
  })
})
