import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Dialogs and notifications',
  description: 'Synthetic Trust Copilot dialog focus and notification announcements.',
  robots: { index: false, follow: false },
}

/** Apply ?theme=light|dark before paint. Dark stays the default. */
const themeBoot = `(function(){try{var t=new URLSearchParams(location.search).get('theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`

export default function DesignDialogsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
      {children}
    </>
  )
}
