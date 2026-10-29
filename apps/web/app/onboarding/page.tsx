import { WorkspaceInvitation } from '@/components/WorkspaceInvitation'
import { salesContactHref } from '@/lib/sales-contact'

export default function OnboardingPage() {
  return (
    <WorkspaceInvitation
      heading="Welcome to Trust Copilot"
      backHref="/"
      contactHref={salesContactHref()}
    />
  )
}
