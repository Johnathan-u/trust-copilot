import { expect, it } from 'vitest'
import { customerArticleText, publishedPolicy } from '@/lib/trustArticleVersion'

const draft = {
  slug: 'draft-slug',
  title: 'Draft title',
  content: 'draft text',
  published: 1,
  is_policy: true,
  published_version_id: 9,
  published_slug: 'approved-slug',
  published_title: 'Approved title',
  published_content: 'approved text',
  published_is_policy: true,
}

it('shows the published snapshot instead of the live draft', () => {
  expect(customerArticleText(draft)).toEqual({
    slug: 'approved-slug',
    title: 'Approved title',
    content: 'approved text',
  })
  expect(publishedPolicy(draft)).toBe(true)
})

it('hides an unpublished draft from customers', () => {
  const article = { ...draft, published: 0 }
  expect(customerArticleText(article)).toBeNull()
  expect(publishedPolicy(article)).toBe(false)
})

it('keeps a legacy published article that has no version row', () => {
  const legacy = {
    slug: 'legacy',
    title: 'Legacy title',
    content: 'legacy text',
    published: 1,
    is_policy: false,
    published_version_id: null,
  }
  expect(customerArticleText(legacy)).toEqual({
    slug: 'legacy',
    title: 'Legacy title',
    content: 'legacy text',
  })
  expect(publishedPolicy(legacy)).toBe(false)
})
