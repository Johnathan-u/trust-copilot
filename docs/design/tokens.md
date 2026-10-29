# Design tokens

Semantic color, type, spacing and interaction tokens for the Trust Copilot web app. Runtime values are CSS custom properties in `apps/web/app/globals.css`. The checked contract is `apps/web/lib/design-tokens.ts`.

Dark is the default product theme (`:root`). That default is a coordinator decision: the product does not switch to light. Light uses the same names under `html[data-theme="light"]`. A public, noindex showcase is at `/design-tokens?theme=dark` and `/design-tokens?theme=light`. CI job `web-release-e2e` runs `apps/web/e2e/release/design-tokens.spec.ts` (Playwright and axe) on every push and pull request and fails on a test failure or any axe violation.

## Typography

Inter is self-hosted with `next/font/local` from `apps/web/app/fonts`. The token is `--font-inter`, then the system stack `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. The app does not request a third-party font host. Sizes are the compact product scale:

| Role     | Size / line | Utility            |
| -------- | ----------- | ------------------ |
| Caption  | 12 / 16     | `text-tc-caption`  |
| Label    | 14 / 20     | `text-tc-label`    |
| Body     | 16 / 24     | `text-tc-body`     |
| Title    | 20 / 28     | `text-tc-title`    |
| Headline | 28 / 36     | `text-tc-headline` |

14px label text is normal text for WCAG, so it uses the 4.5:1 target. Large text (18pt / 24px, or 14pt bold) is not used to lower that target.

## License inventory

| Font  | License                   | Version                  | Source                                                             | Files                                                                                                                                    |
| ----- | ------------------------- | ------------------------ | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Inter | SIL Open Font License 1.1 | 4.1 (release 2024-11-16) | [rsms/inter v4.1](https://github.com/rsms/inter/releases/tag/v4.1) | `apps/web/app/fonts/InterVariable.woff2`, `apps/web/app/fonts/InterVariable-Italic.woff2`, license text `apps/web/app/fonts/LICENSE.txt` |

Copyright (c) 2016 The Inter Project Authors. The files are the upstream variable web fonts from that release. They are bundled in the repo and served from this origin.

## Spacing

The base unit is 4px. Use these steps for padding, margin and gap. Do not invent off-scale spacing for new UI.

| Token           | Pixels | Tailwind             |
| --------------- | ------ | -------------------- |
| `--tc-space-1`  | 4      | `p-tc-1`, `gap-tc-1` |
| `--tc-space-2`  | 8      | `*-tc-2`             |
| `--tc-space-3`  | 12     | `*-tc-3`             |
| `--tc-space-4`  | 16     | `*-tc-4`             |
| `--tc-space-6`  | 24     | `*-tc-6`             |
| `--tc-space-8`  | 32     | `*-tc-8`             |
| `--tc-space-12` | 48     | `*-tc-12`            |

Corner radius is separate from the spacing scale. Cards keep the existing 18px radius (`rounded-tc`). Controls use 12px (`rounded-tc-sm`) and compact chips use 8px (`rounded-tc-xs`).

## Color roles

Use the role, not a raw hex, in components.

- Surfaces: `--tc-bg`, `--tc-surface`, `--tc-surface-raised`, `--tc-surface-sunken`, `--tc-surface-overlay`, `--tc-sidebar`, `--tc-panel`.
- Text: `--tc-text`, `--tc-muted`, `--tc-soft`.
- Brand text and links: `--tc-primary` (and `--tc-primary-2` where a second brand text color is already used).
- Filled controls: `--tc-primary-solid` with `--tc-on-primary`, and `--tc-danger-solid` with `--tc-on-danger`. Do not put `--tc-primary` text on a primary-tinted fill.
- Status: `--tc-success`, `--tc-warning`, `--tc-danger`, `--tc-info`, each on its `*-surface` token. Status is never color alone; pair it with a word.
- Focus: `--tc-focus`, drawn as a 2px solid outline with a 2px offset.
- Disabled: `--tc-disabled-fg` on `--tc-disabled-bg`, with `--tc-disabled-border`.
- Hairline `--tc-border` is decorative. Inputs and other identifiable controls use `--tc-border-strong`.

Light theme surfaces are slate (`#f8fafc`, white, `#f1f5f9`) with teal primary `#0f766e`. Dark keeps the existing navy surfaces and indigo text colors. Filled dark buttons use `#3e4ec0` / `#b91c1c` so white labels clear 4.5:1. White on the older `#5b7cff` and `#ef4444` fills does not.

## Contrast targets

Chosen WCAG 2.2 AA targets, checked in `lib/design-tokens.test.ts` and on the showcase:

- Active text and status pairs: **4.5:1**.
- Focus ring, strong borders and the active navigation border: **3:1** against the surface they sit on.
- Disabled text is inactive UI, so WCAG 1.4.3 does not require 4.5:1. It still has to stay at least **3:1** against the disabled surface.

The dark page background is a gradient. Glow alphas are 0.08 (indigo) and 0.06 (green) so the lightest composited pixels (`#101a31` and `#091b25`) still clear 4.5:1 for every text role, including danger. The glass panel (`rgba(12, 21, 38, 0.82)`) is composited over those glows in the unit test.

`--tc-nav-active-bg` is only a surface for the active label (`--tc-text`). Other text roles are not required to pass on that tint.

Set the theme on `<html>`, not a nested wrapper, so `body` and the grid overlay inherit it:

```text
<html data-theme="light">
```

An unknown value does not switch the theme. Dark stays the default.

## Interaction

- Minimum target size: 24px (WCAG 2.2 SC 2.5.8 AA), via `--tc-target-min` and `min-h-tc-6`.
- Motion: `--tc-duration-fast` 150ms, `--tc-duration-normal` 200ms, `--tc-ease`.
- `prefers-reduced-motion: reduce` sets both durations to 0ms and removes the toast opacity transition. It does not remove every animation in the app.
- Dialogs and toasts: `apps/web/components/ui/Dialog.tsx` traps focus for real dialogs. The notifications panel is a disclosure popover (`aria-expanded` and `aria-controls` on the bell), with no focus trap and no inert background. Escape and an outside click close it and return focus to the bell. One `role="status"` polite region and one `role="alert"` assertive region stay mounted, and each toast's text is inserted into the matching region. Success, info and warning toasts leave after 4000ms. A toast with an action button does not auto-dismiss, so the action has no time limit (WCAG 2.2.1). Errors stay until dismissed. A synthetic check page is `/design-dialogs`. The mobile navigation drawer uses this same dialog primitive with `placement="drawer-start"`. The drawer panel leaves a 2.75rem backdrop strip so a 320px viewport can dismiss it by tap. The polite and assertive toast regions stay outside the dialog inert background.

## Applying tokens

Shared controls in `apps/web/components/ui` and the dashboard sidebar read these tokens. Tailwind color utilities that point at `var(--tc-*)` do not support opacity modifiers such as `bg-tc-surface/60`.

API error text uses `apiErrorPresentation()` in `lib/api-error.ts`. The formatted message is unchanged. The status is always `danger`, so a failure or denial is shown with the danger tokens and does not echo unrelated fields.

Page sections use the same tokens for loading, empty, error, and partial success. A skeleton is not the only feedback for longer than 8 seconds. After that, a status region offers retry. An error uses `role="alert"`, a text label, and a retry button. Empty and error are different states. The words come from `presentHttpFailure()` and do not include status codes or account-role names. See `docs/release/tickets/TC-14-005.md`.
