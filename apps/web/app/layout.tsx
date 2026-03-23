// Global styles (Tailwind + CSS variables) — must load for all pages
import '@/app/globals.css'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased min-h-full overflow-x-hidden">{children}</body>
    </html>
  );
}
