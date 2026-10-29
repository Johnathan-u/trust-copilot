import { WorkspaceCreationEntry } from '@/components/WorkspaceCreationEntry'
import { salesContactHref } from '@/lib/sales-contact'

export default function OnboardingPage() {
  return (
    <WorkspaceCreationEntry
      heading="Welcome to Trust Copilot"
      backHref="/"
      contactHref={salesContactHref()}
      showFormWhenAllowed
    />
  )
}
