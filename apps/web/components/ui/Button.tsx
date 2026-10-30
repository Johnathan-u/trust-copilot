'use client'

import { forwardRef } from 'react'
import { Spinner } from './Spinner'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
}

const variants: Record<Variant, string> = {
  primary:
    'border border-transparent bg-tc-primary-solid text-tc-on-primary hover:bg-[var(--tc-primary-solid-hover)]',
  secondary:
    'border border-tc-border-strong bg-tc-surface-raised text-tc-text hover:bg-[var(--tc-hover)]',
  ghost:
    'border border-transparent bg-transparent text-tc-text hover:bg-[var(--tc-hover)]',
  danger:
    'border border-transparent bg-[var(--tc-danger-solid)] text-[var(--tc-on-danger)] hover:bg-[var(--tc-danger-solid-hover)]',
}

const sizes: Record<string, string> = {
  sm: 'min-h-tc-6 rounded-tc-sm px-tc-3 py-tc-1 text-tc-label',
  md: 'min-h-tc-8 rounded-tc-sm px-tc-4 py-tc-3 text-tc-label',
  lg: 'min-h-tc-12 rounded-tc-sm px-tc-6 py-tc-4 text-tc-body',
}

const spinnerSizes: Record<string, 'sm' | 'md'> = {
  sm: 'sm',
  md: 'sm',
  lg: 'md',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      className = '',
      children,
      disabled,
      ...props
    },
    ref
  ) => (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center gap-tc-2 font-semibold ${variant === 'ghost' ? 'transition-[background-color,border-color,text-decoration-color,fill,stroke]' : 'transition-colors'} duration-[var(--tc-duration-fast)] ease-[var(--tc-ease)] disabled:cursor-not-allowed disabled:border-[var(--tc-disabled-border)] disabled:bg-[var(--tc-disabled-bg)] disabled:text-[var(--tc-disabled-fg)] disabled:hover:bg-[var(--tc-disabled-bg)] ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
      aria-busy={loading || props['aria-busy'] ? true : undefined}
      disabled={disabled || loading}
    >
      {loading && <Spinner size={spinnerSizes[size]} />}
      {children}
    </button>
  )
)

Button.displayName = 'Button'
