// TC-02-006: frontend lint gate (ESLint flat config).
// Rule sets: ESLint recommended, typescript-eslint recommended, React Hooks
// (rules-of-hooks + exhaustive-deps + React Compiler checks) and the Next.js
// core-web-vitals rules. Run with `npm run lint` (warnings fail the gate).
// Directive comments must name the rules they suppress and carry a same-line
// justification. Unused directive comments fail the gate.
import eslintComments from '@eslint-community/eslint-plugin-eslint-comments'
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
    plugins: {
      'eslint-comments': eslintComments,
    },
    linterOptions: {
      reportUnusedDisableDirectives: 'error',
    },
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      // Blanket suppressions, and any suppression without a same-line reason,
      // fail lint. The CI lint step runs this config with --max-warnings=0.
      'eslint-comments/no-unlimited-disable': 'error',
      'eslint-comments/require-description': 'error',
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
      // React Compiler diagnostic for the fetch-on-mount pattern
      // (`useEffect(() => { setLoading(true); fetch(...) })`) used across the
      // dashboard. The app does not enable the React Compiler, the pattern is
      // correct React 19 code, and rewriting ~30 data-loading effects is out of
      // scope for a gate ticket. Follow-up: migrate to a data-fetching hook and
      // re-enable. All other React Hooks/Compiler rules stay at "error".
      'react-hooks/set-state-in-effect': 'off',
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
