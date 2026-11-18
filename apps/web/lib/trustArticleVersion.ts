/** Fields the trust-article API adds for an approved version. Draft text stays on the article. */
export type TrustArticleVersionFields = {
  slug: string
  title: string
  content: string | null
  published: number
  is_policy?: boolean
  published_version_id?: number | null
  published_slug?: string | null
  published_title?: string | null
  published_content?: string | null
  published_is_policy?: boolean | null
}

export type CustomerArticleText = {
  slug: string
  title: string
  content: string | null
}

/**
 * Text a customer can see. A published version wins over the live draft.
 * An unpublished article has no customer text.
 */
export function customerArticleText(
  article: TrustArticleVersionFields
): CustomerArticleText | null {
  if (article.published !== 1) return null
  if (article.published_version_id != null) {
    return {
      slug: article.published_slug || article.slug,
      title: article.published_title || article.title,
      content: article.published_content ?? '',
    }
  }
  return {
    slug: article.slug,
    title: article.title,
    content: article.content,
  }
}

/** True when the published snapshot is a policy the reader can acknowledge. */
export function publishedPolicy(article: TrustArticleVersionFields): boolean {
  const visible = customerArticleText(article)
  if (!visible) return false
  if (article.published_version_id != null)
    return article.published_is_policy === true
  return article.is_policy === true
}
