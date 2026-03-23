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
    'tc-btn-primary border border-[rgba(124,150,255,0.5)] text-white hover:opacity-95 shadow-[0_12px_28px_rgba(91,124,255,0.28)]',
  secondary:
    'border border-[var(--tc-border)] bg-white/5 text-[var(--tc-text)] hover:bg-white/10',
  ghost: 'tc-btn-ghost hover:bg-white/5',
  danger:
    'bg-[var(--tc-danger)] text-white border border-red-500/30 hover:opacity-90',
}

const sizes: Record<string, string> = {
  sm: 'px-2.5 py-1.5 text-sm rounded-xl',
  md: 'px-4 py-3 text-sm rounded-xl',
  lg: 'px-5 py-3.5 text-base rounded-xl',
}

const spinnerSizes: Record<string, 'sm' | 'md'> = {
  sm: 'sm',
  md: 'sm',
  lg: 'md',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading = false, className = '', children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center gap-2 font-semibold transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed hover:translate-y-[-1px] active:translate-y-0 ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner size={spinnerSizes[size]} />}
      {children}
    </button>
  )
)

Button.displayName = 'Button'
