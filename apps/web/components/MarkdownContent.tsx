'use client'

import ReactMarkdown from 'react-markdown'

/** Renders markdown safely (react-markdown escapes HTML by default). TC-R-F1 */
export function MarkdownContent({ content, className = '' }: { content: string; className?: string }) {
  if (!content) return null
  return (
    <div className={`prose prose-sm max-w-none dark:prose-invert ${className}`}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
