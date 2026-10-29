import { WorkspaceCreationEntry } from '@/components/WorkspaceCreationEntry'
import { salesContactHref } from '@/lib/sales-contact'

export default function CheckoutPage() {
  return (
    <WorkspaceCreationEntry
      heading="Trust Copilot"
      backHref="/pricing"
      contactHref={salesContactHref()}
    />
  )
}
