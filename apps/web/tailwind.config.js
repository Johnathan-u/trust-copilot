/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/dialog.ts',
  ],
  theme: {
    extend: {
      colors: {
        tc: {
          bg: 'var(--tc-bg)',
          surface: 'var(--tc-surface)',
          'surface-raised': 'var(--tc-surface-raised)',
          'surface-sunken': 'var(--tc-surface-sunken)',
          panel: 'var(--tc-panel)',
          border: 'var(--tc-border)',
          'border-strong': 'var(--tc-border-strong)',
          text: 'var(--tc-text)',
          muted: 'var(--tc-muted)',
          soft: 'var(--tc-soft)',
          primary: 'var(--tc-primary)',
          'primary-solid': 'var(--tc-primary-solid)',
          'on-primary': 'var(--tc-on-primary)',
          focus: 'var(--tc-focus)',
          success: 'var(--tc-success)',
          warning: 'var(--tc-warning)',
          danger: 'var(--tc-danger)',
          info: 'var(--tc-info)',
          disabled: 'var(--tc-disabled-fg)',
        },
      },
      spacing: {
        'tc-1': 'var(--tc-space-1)',
        'tc-2': 'var(--tc-space-2)',
        'tc-3': 'var(--tc-space-3)',
        'tc-4': 'var(--tc-space-4)',
        'tc-6': 'var(--tc-space-6)',
        'tc-8': 'var(--tc-space-8)',
        'tc-12': 'var(--tc-space-12)',
      },
      fontSize: {
        'tc-caption': [
          'var(--tc-font-size-caption)',
          { lineHeight: 'var(--tc-line-caption)' },
        ],
        'tc-label': [
          'var(--tc-font-size-label)',
          { lineHeight: 'var(--tc-line-label)' },
        ],
        'tc-body': [
          'var(--tc-font-size-body)',
          { lineHeight: 'var(--tc-line-body)' },
        ],
        'tc-title': [
          'var(--tc-font-size-title)',
          { lineHeight: 'var(--tc-line-title)' },
        ],
        'tc-headline': [
          'var(--tc-font-size-headline)',
          { lineHeight: 'var(--tc-line-headline)' },
        ],
      },
      borderRadius: {
        tc: 'var(--tc-radius)',
        'tc-sm': 'var(--tc-radius-sm)',
        'tc-xs': 'var(--tc-radius-xs)',
      },
      backdropBlur: {
        tc: '18px',
      },
    },
  },
  plugins: [],
}
