'use client'

import { forwardRef, useId } from 'react'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', id, ...props }, ref) => {
    const generatedId = useId()
    const inputId = id ?? generatedId
    const errorId = error ? `${inputId}-error` : undefined
    return (
      <div className="w-full">
        {label && (
          <label
            htmlFor={inputId}
            className="mb-tc-1 block text-tc-label font-medium text-tc-muted"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          suppressHydrationWarning
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId}
          className={`w-full rounded-tc-sm border border-tc-border-strong bg-tc-surface-overlay px-tc-3 py-tc-2 text-tc-body text-tc-text placeholder:text-tc-muted disabled:cursor-not-allowed disabled:border-[var(--tc-disabled-border)] disabled:bg-[var(--tc-disabled-bg)] disabled:text-[var(--tc-disabled-fg)] ${error ? 'border-tc-danger' : ''} ${className}`}
          {...props}
        />
        {error && (
          <p
            id={errorId}
            role="alert"
            className="mt-tc-1 text-tc-label text-tc-danger"
          >
            {error}
          </p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
