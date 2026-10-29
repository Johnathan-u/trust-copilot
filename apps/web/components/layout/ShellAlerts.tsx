'use client'

import { createContext, useContext } from 'react'
import { listFromPayload, readSectionJson } from '@/lib/section-load'
import { useSectionQuery } from '@/components/ui/useSectionQuery'

export type ShellAlert = {
  id: number
  action: string
  occurred_at: string | null
  details: string | null
}

type ShellAlertsValue = ReturnType<typeof useSectionQuery<ShellAlert>>

const ShellAlertsContext = createContext<ShellAlertsValue | null>(null)

export function ShellAlertsProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const query = useSectionQuery<ShellAlert>({
    load: async (signal) => {
      const response = await fetch('/api/auth/alerts', {
        credentials: 'include',
        signal,
      })
      const data = await readSectionJson(response)
      return listFromPayload<ShellAlert>(data, ['alerts'])
    },
    deps: [],
  })

  return (
    <ShellAlertsContext.Provider value={query}>
      {children}
    </ShellAlertsContext.Provider>
  )
}

export function useShellAlerts(): ShellAlertsValue {
  const value = useContext(ShellAlertsContext)
  if (!value) {
    throw new Error('useShellAlerts must be used within ShellAlertsProvider')
  }
  return value
}
