# TC-14-001d evidence

Public and marketing pages, plus `components/CommandPalette.tsx`, now use the existing `--tc-*` tokens. No new palette value was added. The raw-colour gate scans `apps/web/app` and `apps/web/components` and skips `app/globals.css`.

This file does not accept TC-14-001 or TC-14-001d. The child is not counted toward DONE.

## Gate

Detector: `apps/web/tests/unit/ui-raw-palette.test.ts`.
Command, from `apps/web`: `npx vitest run tests/unit/ui-raw-palette.test.ts --reporter=verbose`.
Node v24.22.1. Vitest 5.0.5.

| Run | Tree | app hits | components hits | Exit |
| --- | --- | ---: | ---: | ---: |
| Failing-before | master `d69109e720df3a697ff4af9eb1b222ae1553a628` with only the widened test | 93 in 7 files | 2 in `CommandPalette.tsx` | 1 |
| Passing-after | this branch after the token move | 0 | 0 | 0 |

Failing-before file counts, same as the re-verify note at `1241fe47`: `page.tsx` 31, `vendor-response/page.tsx` 22, `pricing/page.tsx` 16, `login/page.tsx` 15, `register/page.tsx` 5, `trust/[slug]/page.tsx` 3, `forgot-password/page.tsx` 1, `CommandPalette.tsx` 2. `app/globals.css` stays outside the gate. Logs: `failing-before.txt`, `passing-after.txt`.

The original four tests still cover `components/ui`, `app/dashboard`, and `components/layout`. The new test is the wider scan. `npm run test:unit` on this tree: 59 files, 545 passed.

## What changed

Raw classes and hex/rgb colours map onto the closest existing token. Status text sits on the matching `*-surface` token. The shell's selected row (`--tc-nav-active-bg`) and hover wash (`--tc-hover`) are reused. Filled controls use `tc-btn-primary`. The product mark uses `--tc-brand-mark`, `--tc-on-primary`, and `--tc-brand-mark-shadow`, which is what the top bar already does.

`hover:opacity-90` on the existing marketing `.tc-btn-primary` links was left in place. That contrast follow-up stays with TC-14-002.

## Judgment calls

These raw colours have no token at the same alpha or stop. Each one uses the nearest semantic token.

- `bg-white/5` (0.05) and `hover:bg-white/5` use `--tc-hover` (0.06). Form wells, the checkbox, and the forgot-password note use `--tc-surface-sunken`. The trust textarea uses `--tc-surface-overlay`, the input fill. The demo button rest uses `bg-tc-surface-raised` so its hover wash is still visible.
- `bg-white/10` on the selected command-palette row uses `--tc-nav-active-bg`. There is no 10% wash token. `hover:bg-white/10` uses `--tc-hover` (0.06 rather than 0.10).
- The logo gradient `#7c96ff`, `#5b7cff`, `#2dd4bf` uses `--tc-brand-mark`. `#2dd4bf` has no token. Home and pricing marks now set `--tc-on-primary`. They used to inherit `--tc-text`, which is dark in the light theme, and the mark token is dark in both themes.
- Logo shadows `0 8px 20px rgba(91,124,255,0.3)` and `0 12px 30px rgba(91,124,255,0.35)` use `--tc-brand-mark-shadow` (`0 12px 30px rgba(62,78,192,0.35)`).
- The sticky nav `rgba(8,17,31,0.82)` uses `--tc-panel` (`rgba(12,21,38,0.82)`). The alpha matches. In the light theme the old bar stayed navy while text tokens go dark; the panel token follows the theme.
- Primary washes at 8% and 10% use `--tc-surface-glow-primary`. Over `#08111f` those washes composite near `#101a31`. `--tc-chip` in the light theme (`#dbeafe`) with light `--tc-primary-2` (`#0f766e`) is 4.49:1, under the 4.5 target, so the chip token was not used for that text.
- Primary borders at 25%, 30%, and 40% use `border-tc-primary`. There is no alpha border token.
- The annual switch, when on, uses `--tc-nav-active-bg`. A 25% primary fill over `#08111f` is about `#1d2c57`; the token is `#1c2748`.
- Hero glows at 18% and 14% primary use `--tc-surface-glow-primary` as the gradient stop. That token is the 8% composite the contrast contract already checks. The light-theme glow is the flat page colour.
- The "Save" chip (`rgba(34,197,94,0.12)` / `0.18`) uses `--tc-success-surface` and `border-tc-success`. `#22c55e` is `--tc-success`. Dark contrast of that pair is about 5.88:1 (the 12% wash was about 7.8:1). Light contrast rises from about 6.19:1 to 6.49:1.
- Card glows `0 0 40px` / `0 0 60px` of primary at 8% and 6% use `--tc-shadow`. That is the only shadow token.
- `text-red-400` (`#f87171`) uses `--tc-danger` (`#ef4444`). On `#08111f` the ratio drops from about 6.84:1 to 5.03:1 and stays on a tested pair. In the light theme the raw red-400 on a light page fails; the danger token passes.
- Trust intake errors `bg-red-500/10 text-red-400` use `--tc-danger-surface` and `--tc-danger`.
- The vendor spinner `#5b7cff` is `--tc-primary`. Its focus ring `#5b7cff` at 40% uses solid `--tc-focus` (`#7c96ff` in the dark theme). There is no 40% focus token.
- The vendor submit button `#5b7cff` / hover `#4a6ae8` / active `#3b5bdb` uses `tc-btn-primary`. Those hover and active hexes have no tokens. Hover is `--tc-primary-solid-hover`. White on `#5b7cff` does not clear 4.5:1; `--tc-on-primary` on `--tc-primary-solid` does.
- Stale fallbacks `#0c0e14` and `#e4e6ea` inside `var()` were removed. They are not the current token values.
- Vendor status washes (amber, blue, emerald, slate) use the warning, info, and success surfaces, or `--tc-surface-sunken` with `--tc-muted`. That matches the dashboard request badges.

## Checks

From `apps/web`, Node v24.22.1:

| Command | Result |
| --- | --- |
| `npm run lint` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run test:unit` | 59 files, 545 passed, exit 0 |
| `pre-commit run --files` on the changed frontend files | passed |

`apps/web/e2e/release/design-tokens.spec.ts` and the theme screenshots cover `/design-tokens`, not these pages. That spec was not re-run, and the committed theme screenshots were not rewritten.

Axe (`@axe-core/playwright` 4.14.0, Chromium 1248) on the running dev server, after `data-theme` was set and colours had settled. `--tc-bg` was `#08111f` in dark and `#f8fafc` in light. Colour-contrast violations: 0 on `/`, `/pricing`, `/login`, `/register`, `/forgot-password`, and `/vendor-response`, in both themes, at 1440px. Login, register, and forgot-password had 0 violations of any rule. Home and pricing still report the unnamed billing switch (`button-name`) and the missing main landmark (`landmark-one-main`, `region`). Vendor response still reports a missing main landmark and heading. Those are existing structure, not colour, and this ticket does not redesign them. The home and pricing annual switches still flip the price to $250.

Computed mark after the change: dark `rgb(62, 78, 192)` with white text and nav `rgba(12, 21, 38, 0.82)`; light `rgb(15, 118, 110)` with white text. Those are `--tc-brand-mark`, `--tc-on-primary`, and `--tc-panel`.

## CI

Run IDs are in `ci-runs.md` once both events are green on the final head.
