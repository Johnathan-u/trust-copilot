import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Design tokens',
  description:
    'Synthetic Trust Copilot typography, color, spacing and interaction tokens.',
  robots: { index: false, follow: false },
}

/** Apply ?theme=light|dark before paint so the page background uses the same tokens. */
const themeBoot = `(function(){try{var t=new URLSearchParams(location.search).get('theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`

export default function DesignTokensLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
      {children}
    </>
  )
}
