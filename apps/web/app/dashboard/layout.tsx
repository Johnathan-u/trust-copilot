import { AuthProvider } from '@/contexts/AuthContext'
import { AISettingsProvider } from '@/contexts/AISettingsContext'
import { DashboardShell } from '@/components/layout/DashboardShell'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <AuthProvider>
      <AISettingsProvider>
        <DashboardShell>{children}</DashboardShell>
      </AISettingsProvider>
    </AuthProvider>
  )
}
