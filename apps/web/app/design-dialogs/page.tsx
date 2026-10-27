import { DialogShowcase } from './showcase'
import type { ThemeName } from '@/lib/design-tokens'

function themeFromQuery(value: string | undefined): ThemeName {
  return value === 'light' ? 'light' : 'dark'
}

export default async function DesignDialogsPage({
  searchParams,
}: {
  searchParams: Promise<{ theme?: string | string[] }>
}) {
  const query = await searchParams
  const requested = Array.isArray(query.theme) ? query.theme[0] : query.theme
  const theme = themeFromQuery(requested)
  return <DialogShowcase theme={theme} />
}
