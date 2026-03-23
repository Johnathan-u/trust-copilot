/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        tc: {
          bg: 'var(--tc-bg)',
          panel: 'var(--tc-panel)',
          border: 'var(--tc-border)',
          text: 'var(--tc-text)',
          muted: 'var(--tc-muted)',
          soft: 'var(--tc-soft)',
          primary: 'var(--tc-primary)',
          success: 'var(--tc-success)',
          warning: 'var(--tc-warning)',
          danger: 'var(--tc-danger)',
        },
      },
      borderRadius: {
        'tc': 'var(--tc-radius)',
        'tc-sm': 'var(--tc-radius-sm)',
      },
      backdropBlur: {
        tc: '18px',
      },
    },
  },
  plugins: [],
}
