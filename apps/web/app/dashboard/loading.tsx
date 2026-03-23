import { ListSkeleton } from '@/components/ui/Skeleton'
import { Skeleton } from '@/components/ui/Skeleton'

export default function DashboardLoading() {
  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <div className="flex items-center justify-between">
        <Skeleton width={200} height={28} />
        <Skeleton width={120} height={36} className="rounded-xl" />
      </div>
      <div
        className="rounded-2xl p-5"
        style={{ background: 'var(--tc-panel)', border: '1px solid var(--tc-border)' }}
      >
        <ListSkeleton rows={6} />
      </div>
    </div>
  )
}
