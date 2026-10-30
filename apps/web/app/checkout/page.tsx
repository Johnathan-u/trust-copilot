import { WorkspaceInvitation } from '@/components/WorkspaceInvitation'
import { salesContactHref } from '@/lib/sales-contact'

export default function CheckoutPage() {
  return (
    <WorkspaceInvitation
      heading="Trust Copilot"
      backHref="/pricing"
      contactHref={salesContactHref()}
    />
  )
}
