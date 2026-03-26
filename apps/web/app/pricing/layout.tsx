import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Pricing',
  description: 'Trust Copilot Pro Plan — $25/month. Evidence-grounded AI for compliance questionnaire automation. Everything included.',
}

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
