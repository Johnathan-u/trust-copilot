'use client'

interface SkeletonProps {
  className?: string
  width?: string | number
  height?: string | number
}

export function Skeleton({ className = '', width, height }: SkeletonProps) {
  const style: React.CSSProperties = {}
  if (width != null) style.width = typeof width === 'number' ? `${width}px` : width
  if (height != null) style.height = typeof height === 'number' ? `${height}px` : height
  return (
    <div
      className={`animate-pulse rounded-lg bg-[var(--tc-border)]/60 ${className}`}
      style={style}
      aria-hidden
    />
  )
}

/** @deprecated Use ListSkeleton instead */
export const DocumentListSkeleton = () => <ListSkeleton />
/** @deprecated Use ListSkeleton instead */
export const QuestionnaireListSkeleton = () => <ListSkeleton />

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <ul className="divide-y divide-white/10">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="flex items-center justify-between py-3">
          <div className="space-y-1 min-w-0 flex-1">
            <Skeleton width="50%" height={18} />
            <Skeleton width="35%" height={14} />
          </div>
          <Skeleton width={72} height={28} className="rounded-xl shrink-0" />
        </li>
      ))}
    </ul>
  )
}

export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr>
            {Array.from({ length: cols }, (_, i) => (
              <th key={i} className="pb-2 pr-4 text-left">
                <Skeleton height={16} width={i === 0 ? 120 : 80} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/10">
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }, (_, c) => (
                <td key={c} className="py-3 pr-4">
                  <Skeleton height={18} width={c === 0 ? '90%' : 70} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
