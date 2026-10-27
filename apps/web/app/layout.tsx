// Global styles (Tailwind + CSS variables) — must load for all pages
import '@/app/globals.css'
import type { Metadata } from 'next'
import localFont from 'next/font/local'

const inter = localFont({
  src: [
    { path: './fonts/InterVariable.woff2', weight: '100 900', style: 'normal' },
    { path: './fonts/InterVariable-Italic.woff2', weight: '100 900', style: 'italic' },
  ],
  variable: '--font-inter',
  display: 'swap',
  adjustFontFallback: false,
  fallback: ['ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
})

export const metadata: Metadata = {
  title: {
    default: 'Trust Copilot — Compliance questionnaires, answered with evidence',
    template: '%s | Trust Copilot',
  },
  description: 'Upload your evidence documents and compliance questionnaires. Get AI-generated answers grounded in your real evidence — not hallucinations.',
  icons: {
    icon: '/icon.svg',
  },
  openGraph: {
    title: 'Trust Copilot — Compliance questionnaires, answered with evidence',
    description: 'Evidence-grounded AI for security and compliance questionnaire automation. Upload evidence, upload the questionnaire, get answers.',
    type: 'website',
    siteName: 'Trust Copilot',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Trust Copilot',
    description: 'Evidence-grounded AI for compliance questionnaire automation.',
  },
  robots: {
    index: true,
    follow: true,
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className={`${inter.className} antialiased min-h-full overflow-x-hidden`}>{children}</body>
    </html>
  );
}
