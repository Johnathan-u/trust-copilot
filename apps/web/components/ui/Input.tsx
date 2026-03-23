'use client'

import { forwardRef } from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', ...props }, ref) => (
    <div className="w-full">
      {label && (
        <label className="mb-1 block text-sm font-medium text-[var(--tc-muted)]">
          {label}
        </label>
      )}
      <input
        ref={ref}
        suppressHydrationWarning
        className={`w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2.5 text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:border-[var(--tc-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)] ${error ? 'border-[var(--tc-danger)]' : ''} ${className}`}
        {...props}
      />
      {error && <p className="mt-1 text-sm text-[var(--tc-danger)]">{error}</p>}
    </div>
  )
)

Input.displayName = 'Input'
