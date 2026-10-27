import { DialogShowcase } from './showcase'
import type { ThemeName } from '@/lib/design-tokens'

function themeFromQuery(value: string | undefined): ThemeName {
  return value === 'light' ? 'light' : 'dark'
}

export default function DesignDialogsPage({
  searchParams,
}: {
  searchParams?: { theme?: string }
}) {
  const theme = themeFromQuery(searchParams?.theme)
  return <DialogShowcase theme={theme} />
}
