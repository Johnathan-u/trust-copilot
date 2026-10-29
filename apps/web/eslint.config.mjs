// TC-02-006: frontend lint gate (ESLint flat config).
// Rule sets: ESLint recommended, typescript-eslint recommended, React Hooks
// (rules-of-hooks + exhaustive-deps + React Compiler checks) and the Next.js
// core-web-vitals rules. Run with `npm run lint` (warnings fail the gate).
import js from '@eslint/js'
import nextPlugin from '@next/eslint-plugin-next'
import reactHooks from 'eslint-plugin-react-hooks'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores([
    'node_modules/**',
    '.next/**',
    '.next-e2e-sales/**',
    'out/**',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
    'next-env.d.ts',
  ]),
  js.configs.recommended,
  tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  nextPlugin.configs['core-web-vitals'],
  {
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      // Allow intentionally unused args/vars when prefixed with "_".
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // TC-02-006b: synchronous setState inside an effect is an error.
      // Fetch results belong in the async callback. Resets happen during
      // render. Event handlers may set state directly.
      'react-hooks/set-state-in-effect': 'error',
    },
  },
  {
    // Node-side files: configs, Playwright specs and helper scripts.
    files: ['*.{js,mjs,cjs,ts}', 'scripts/**/*.js', 'e2e/**/*.ts'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    // CommonJS config/scripts legitimately use require().
    files: ['**/*.{js,cjs}'],
    languageOptions: { sourceType: 'commonjs' },
    rules: { '@typescript-eslint/no-require-imports': 'off' },
  },
])
