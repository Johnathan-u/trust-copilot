import { Button, Input } from '@/components/ui'
import {
  disabledContrastPair,
  requiredContrastPairs,
  spacingScale,
  type ThemeName,
} from '@/lib/design-tokens'

const typeSamples = [
  { id: 'caption', className: 'text-tc-caption', label: 'Caption 12 / 16' },
  { id: 'label', className: 'text-tc-label', label: 'Label 14 / 20' },
  { id: 'body', className: 'text-tc-body', label: 'Body 16 / 24' },
  { id: 'title', className: 'text-tc-title', label: 'Title 20 / 28' },
  { id: 'headline', className: 'text-tc-headline', label: 'Headline 28 / 36' },
] as const

const statusSamples = [
  {
    name: 'Success',
    detail: 'Saved',
    fg: '--tc-success',
    bg: '--tc-success-surface',
  },
  {
    name: 'Warning',
    detail: 'Needs review',
    fg: '--tc-warning',
    bg: '--tc-warning-surface',
  },
  {
    name: 'Danger',
    detail: 'Failed',
    fg: '--tc-danger',
    bg: '--tc-danger-surface',
  },
  {
    name: 'Info',
    detail: 'In progress',
    fg: '--tc-info',
    bg: '--tc-info-surface',
  },
] as const

function themeFromQuery(value: string | undefined): ThemeName {
  return value === 'light' ? 'light' : 'dark'
}

export default async function DesignTokensPage({
  searchParams,
}: {
  searchParams: Promise<{ theme?: string | string[] }>
}) {
  const query = await searchParams
  const requested = Array.isArray(query.theme) ? query.theme[0] : query.theme
  const theme = themeFromQuery(requested)
  const pairs = [...requiredContrastPairs(), disabledContrastPair()]

  return (
    <main
      id="token-showcase"
      data-testid="token-showcase"
      data-expected-theme={theme}
      className="relative z-[1] min-h-screen text-tc-text"
      style={{ background: 'var(--tc-body-background)' }}
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-tc-8 px-tc-4 py-tc-6">
        <header className="flex flex-col gap-tc-4">
          <p className="text-tc-caption font-semibold uppercase tracking-wider text-tc-muted">
            Trust Copilot
          </p>
          <h1 className="text-tc-headline font-bold">Design tokens</h1>
          <p className="max-w-3xl text-tc-body text-tc-muted">
            Synthetic showcase of type, the 4px spacing scale, and semantic
            surface, text, status, focus and disabled colors. No customer data
            is shown.
          </p>
          <nav aria-label="Theme" className="flex flex-wrap gap-tc-2">
            {(['dark', 'light'] as const).map((name) => {
              const current = name === theme
              return (
                <a
                  key={name}
                  href={`/design-tokens?theme=${name}`}
                  aria-current={current ? 'page' : undefined}
                  className={`inline-flex min-h-tc-6 items-center rounded-tc-sm border px-tc-3 py-tc-1 text-tc-label font-medium ${
                    current
                      ? 'border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)] text-tc-text'
                      : 'border-tc-border-strong text-tc-muted'
                  }`}
                >
                  {name === 'dark' ? 'Dark theme' : 'Light theme'}
                </a>
              )
            })}
          </nav>
        </header>

        <section
          aria-labelledby="type-heading"
          className="flex flex-col gap-tc-3"
        >
          <h2 id="type-heading" className="text-tc-title font-semibold">
            Typography
          </h2>
          <div className="flex flex-col gap-tc-2">
            {typeSamples.map((sample) => (
              <p
                key={sample.id}
                data-type={sample.id}
                className={`${sample.className} text-tc-text`}
              >
                {sample.label}
              </p>
            ))}
          </div>
        </section>

        <section
          id="spacing"
          aria-labelledby="spacing-heading"
          className="flex flex-col gap-tc-3"
        >
          <h2 id="spacing-heading" className="text-tc-title font-semibold">
            Spacing
          </h2>
          <p className="text-tc-label text-tc-muted">
            Base unit 4px. Named steps: 4, 8, 12, 16, 24, 32, 48.
          </p>
          <ul className="flex flex-col gap-tc-2">
            {spacingScale.map((step) => (
              <li key={step.cssVar} className="flex items-center gap-tc-3">
                <span
                  data-space={step.px}
                  className="inline-block shrink-0 rounded-tc-xs bg-tc-primary-solid"
                  style={{
                    width: `var(${step.cssVar})`,
                    height: `var(${step.cssVar})`,
                  }}
                />
                <span className="text-tc-label text-tc-text">
                  {step.px}px{' '}
                  <span className="text-tc-muted">{step.cssVar}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section
          aria-labelledby="component-heading"
          className="flex flex-col gap-tc-4"
        >
          <h2 id="component-heading" className="text-tc-title font-semibold">
            Components
          </h2>
          <div className="flex flex-wrap gap-tc-3">
            <Button type="button" data-testid="primary-action">
              Primary action
            </Button>
            <Button type="button" variant="secondary">
              Secondary
            </Button>
            <Button type="button" variant="ghost">
              Ghost
            </Button>
            <Button type="button" variant="danger">
              Danger
            </Button>
            <Button type="button" disabled>
              Disabled
            </Button>
          </div>
          <div className="grid gap-tc-4 md:grid-cols-2">
            <Input
              label="Workspace name"
              placeholder="Northwind Security"
              autoComplete="organization"
            />
            <Input
              label="Workspace name"
              error="Enter a workspace name."
              defaultValue=""
            />
          </div>
          <ul className="flex flex-col gap-tc-2">
            {statusSamples.map((status) => (
              <li
                key={status.name}
                className="rounded-tc-sm border px-tc-3 py-tc-2 text-tc-label font-medium"
                style={{
                  color: `var(${status.fg})`,
                  background: `var(${status.bg})`,
                  borderColor: `var(${status.fg})`,
                }}
              >
                {status.name}: {status.detail}
              </li>
            ))}
          </ul>
          <p className="text-tc-body">
            <a className="text-tc-primary underline" href="#spacing">
              Back to spacing
            </a>
          </p>
        </section>

        <section
          aria-labelledby="pairs-heading"
          className="flex flex-col gap-tc-3"
        >
          <h2 id="pairs-heading" className="text-tc-title font-semibold">
            Contrast pairs
          </h2>
          <p className="text-tc-label text-tc-muted">
            Active text and status pairs target 4.5:1. Focus, borders and
            disabled text target 3:1.
          </p>
          <ul className="grid grid-cols-1 gap-tc-2 sm:grid-cols-2">
            {pairs.map((entry) =>
              entry.kind === 'text' ? (
                <li
                  key={entry.id}
                  data-contrast-pair={entry.id}
                  data-fg={entry.fg}
                  data-bg={entry.bg}
                  data-min={entry.min}
                  data-kind={entry.kind}
                  className="break-all rounded-tc-xs px-tc-3 py-tc-2 text-tc-label"
                  style={{
                    color: `var(${entry.fg})`,
                    background: `var(${entry.bg})`,
                  }}
                >
                  {entry.id}
                </li>
              ) : (
                <li
                  key={entry.id}
                  className="flex items-center gap-tc-3 rounded-tc-xs px-tc-3 py-tc-2"
                >
                  <span
                    data-contrast-pair={entry.id}
                    data-fg={entry.fg}
                    data-bg={entry.bg}
                    data-min={entry.min}
                    data-kind={entry.kind}
                    className="inline-block h-tc-6 w-tc-6 shrink-0 rounded-tc-xs border-2"
                    style={{
                      color: `var(${entry.fg})`,
                      background: `var(${entry.bg})`,
                      borderColor: `var(${entry.fg})`,
                    }}
                  />
                  <span className="break-all text-tc-label text-tc-text">
                    {entry.id}
                  </span>
                </li>
              )
            )}
          </ul>
        </section>
      </div>
    </main>
  )
}
