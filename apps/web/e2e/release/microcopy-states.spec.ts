import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-008'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

const syntheticMe = {
  id: 42,
  email: 'synthetic.reviewer@example.com',
  display_name: 'Synthetic Reviewer',
  workspace_id: 7,
  workspace_name: 'Synthetic Workspace',
  workspace_slug: 'synthetic',
  role: 'admin',
  workspaces: [
    { id: 7, name: 'Synthetic Workspace', slug: 'synthetic', role: 'admin' },
  ],
  permissions: {
    can_edit: true,
    can_review: true,
    can_admin: true,
    can_export: true,
  },
  needs_onboarding: false,
  subscription: { status: 'trialing', plan: 'synthetic' },
  mfa_enrolled: true,
  mfa_required_for_workspace: false,
  workspace_auth_policy: { mfa_required: false, session_max_age_seconds: null },
}

const serverNoEvidence =
  'No eligible evidence was found for this question, so no model call was made.'

const questionnaire = {
  id: 9,
  filename: 'synthetic-questions.xlsx',
  questions: [
    {
      id: 3,
      text: 'Synthetic question about access reviews.',
      answer: {
        id: 11,
        text: 'Synthetic draft.',
        status: 'draft',
        citations: '[]',
        outcome_code: 'no_evidence',
        outcome: {
          code: 'no_evidence',
          message: serverNoEvidence,
          request_id: 'synthetic-ref',
          retryable: false,
        },
      },
    },
    {
      id: 4,
      text: 'Synthetic question the model declined to settle.',
      answer: {
        id: 12,
        text: 'Synthetic abstention.',
        status: 'draft',
        citations: '[]',
        outcome_code: 'model_abstained',
        outcome: {
          code: 'model_abstained',
          message:
            'The model reviewed the supplied evidence and judged it insufficient to answer.',
          request_id: 'synthetic-ref',
          retryable: false,
        },
      },
    },
  ],
}

type Hold = 'save' | 'upload' | 'generate' | 'export' | 'approve' | null

let hold: Hold = null
let releaseHold: (() => void) | null = null
let saveResult: 'ok' | 'deny' = 'ok'
let uploadResult: 'ok' | 'format' | 'deny' = 'ok'
let generateResult: 'ok' | 'model' = 'ok'
let exportResult: 'ok' | 'deny' = 'ok'
let approveResult: 'ok' | 'deny' = 'ok'
let generateJobStatus: 'queued' | 'completed' | 'failed' = 'queued'
let exportJobStatus: 'queued' | 'completed' = 'queued'

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

test.beforeEach(() => {
  hold = null
  releaseHold = null
  saveResult = 'ok'
  uploadResult = 'ok'
  generateResult = 'ok'
  exportResult = 'ok'
  approveResult = 'ok'
  generateJobStatus = 'queued'
  exportJobStatus = 'queued'
})

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function deniedBody() {
  return { detail: 'Insufficient permissions for admin role' }
}

async function waitIfHeld(kind: Hold) {
  if (hold !== kind) return
  await new Promise<void>((resolve) => {
    releaseHold = resolve
  })
}

async function installApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (pathname.endsWith('/api/auth/me')) return json(route, syntheticMe)
    if (pathname.includes('/api/auth/alerts'))
      return json(route, { alerts: [] })
    if (pathname.includes('/unread-count')) return json(route, { count: 0 })
    if (pathname.includes('/api/in-app-notifications')) {
      return json(route, { notifications: [] })
    }
    if (pathname.includes('/api/workspaces/current')) {
      return json(route, {
        id: 7,
        name: 'Synthetic Workspace',
        ai_completion_model: 'gpt-4o-mini',
        ai_temperature: 0.35,
      })
    }
    if (pathname.includes('/api/questionnaires/9')) {
      return json(route, questionnaire)
    }
    if (pathname.includes('/api/exports/records')) {
      return json(route, { records: [] })
    }
    if (pathname.includes('/api/documents')) {
      if (method === 'POST' && pathname.includes('/upload')) {
        await waitIfHeld('upload')
        if (uploadResult === 'format') {
          return json(
            route,
            {
              detail:
                'File must have an allowed extension. Allowed: .docx, .pdf, .xlsx',
            },
            400
          )
        }
        if (uploadResult === 'deny') return json(route, deniedBody(), 403)
        return json(route, {
          id: 8,
          filename: 'synthetic.pdf',
          status: 'uploaded',
        })
      }
      return json(route, { documents: [] })
    }
    if (pathname.includes('/api/exports/generate/')) {
      await waitIfHeld('generate')
      if (generateResult === 'model') {
        return json(route, { detail: 'Unsupported model' }, 400)
      }
      return json(route, { job_id: 41, status: 'queued' })
    }
    if (pathname.includes('/api/exports/export/')) {
      await waitIfHeld('export')
      if (exportResult === 'deny') return json(route, deniedBody(), 403)
      return json(route, { job_id: 42, status: 'queued' })
    }
    if (pathname.includes('/api/jobs/41')) {
      return json(route, {
        id: 41,
        status: generateJobStatus,
        error_code: generateJobStatus === 'failed' ? 'no_evidence' : null,
        error: null,
        error_detail:
          generateJobStatus === 'failed'
            ? {
                code: 'no_evidence',
                message: serverNoEvidence,
                request_id: 'synthetic-ref',
                retryable: false,
              }
            : null,
      })
    }
    if (pathname.includes('/api/jobs/42')) {
      return json(route, { id: 42, status: exportJobStatus, error: null })
    }
    if (pathname.includes('/api/answers/bulk')) {
      await waitIfHeld('approve')
      if (approveResult === 'deny') return json(route, deniedBody(), 403)
      return json(route, { updated: 1 })
    }
    if (pathname.includes('/api/answers')) {
      await waitIfHeld('save')
      if (saveResult === 'deny') return json(route, deniedBody(), 403)
      return json(route, {
        id: 11,
        text: 'Synthetic draft revised.',
        status: 'draft',
      })
    }
    return json(route, {})
  })
}

async function openApp(
  page: Page,
  pathname: string,
  width = 1440,
  height = 900
) {
  await page.addInitScript(() => {
    const removeDevPortal = () => {
      document.querySelectorAll('nextjs-portal').forEach((el) => {
        el.setAttribute('inert', '')
        el.remove()
      })
    }
    removeDevPortal()
    new MutationObserver(removeDevPortal).observe(document.documentElement, {
      childList: true,
      subtree: true,
    })
  })
  await installApi(page)
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.setViewportSize({ width, height })
  await page.goto(pathname)
}

function release() {
  const done = releaseHold
  releaseHold = null
  hold = null
  done?.()
}

async function shoot(page: Page, name: string) {
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({
      path: path.join(screenshotDir, `${name}-${width}.png`),
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}

async function writeAxe(
  page: Page,
  state: string,
  theme: 'dark' | 'light',
  viewport: number
) {
  const axe = await new AxeBuilder({ page })
    .include('[data-microcopy="actions"]')
    .include('#tc-toast-live')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const violations = axe.violations.map((item) => ({
    id: item.id,
    impact: item.impact,
    help: item.help,
    nodes: item.nodes.length,
  }))
  writeFileSync(
    path.join(evidenceDir, `axe-${state}-${theme}-${viewport}.json`),
    `${JSON.stringify(
      {
        name: `${state}-${theme}-${viewport}`,
        state,
        theme,
        viewport,
        violationCount: violations.length,
        violations,
        violationDetails: axe.violations,
      },
      null,
      2
    )}\n`
  )
  await test.info().attach(`axe-${state}-${theme}-${viewport}`, {
    path: path.join(evidenceDir, `axe-${state}-${theme}-${viewport}.json`),
    contentType: 'application/json',
  })
  const blocking = violations.filter(
    (item) => item.impact === 'critical' || item.impact === 'serious'
  )
  expect(blocking, JSON.stringify(violations, null, 2)).toEqual([])
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([])
}

test.describe('confirmed action and failure copy', () => {
  test.describe.configure({ timeout: 90_000 })

  test('save stays unconfirmed until the server accepts', async ({ page }) => {
    hold = 'save'
    await openApp(page, '/dashboard/review/9')
    const row = page.locator('[data-save-state="idle"]').first()
    await expect(row).toHaveText('Not saved yet')
    await expect(page.getByText('Saved', { exact: true })).toHaveCount(0)
    const field = page.locator('textarea').first()
    await field.fill('Synthetic draft revised.')
    await field.blur()
    await expect(page.locator('[data-save-state="saving"]').first()).toHaveText(
      'Saving'
    )
    await expect(page.getByText('Saved', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Done', { exact: true })).toHaveCount(0)
    saveResult = 'ok'
    release()
    await expect(page.locator('[data-save-state="saved"]').first()).toHaveText(
      'Saved'
    )
    await shoot(page, 'save-confirmed')
  })

  test('upload stays unconfirmed until the server accepts', async ({
    page,
  }) => {
    hold = 'upload'
    await openApp(page, '/dashboard/documents')
    await expect(
      page.getByRole('button', { name: 'Upload', exact: true }).first()
    ).toBeVisible()
    await page.locator('#doc-upload').setInputFiles({
      name: 'synthetic.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('synthetic'),
    })
    const dialog = page.getByRole('dialog', {
      name: 'Upload Evidence Document',
    })
    await dialog.getByRole('button', { name: 'Upload', exact: true }).click()
    await expect(page.locator('[data-upload-state="pending"]')).toHaveText(
      'Uploading'
    )
    await expect(
      page.getByRole('button', { name: 'Dismiss Uploaded' })
    ).toHaveCount(0)
    uploadResult = 'ok'
    release()
    await expect(
      page.getByRole('status').filter({ hasText: 'Uploaded' })
    ).toBeVisible()
    await expect(page.getByText('The file is stored.')).toBeVisible()
  })

  test('generate stays pending until the job completes', async ({ page }) => {
    hold = 'generate'
    await openApp(page, '/dashboard/review/9')
    const generate = page.locator('[data-generate-state]')
    await expect(generate).toHaveText('Generate')
    await generate.click()
    await expect(generate).toHaveText('Generating')
    await expect(generate).toHaveAttribute('data-generate-state', 'pending')
    await expect(
      page.getByRole('button', { name: 'Dismiss Generated' })
    ).toHaveCount(0)
    generateResult = 'ok'
    release()
    await expect(generate).toHaveText('Generating')
    await expect(
      page.getByRole('button', { name: 'Dismiss Generated' })
    ).toHaveCount(0)
    generateJobStatus = 'completed'
    await expect(
      page.getByRole('status').filter({ hasText: 'Generated' })
    ).toBeVisible()
    await expect(
      page.getByText('Draft answers are ready to review.')
    ).toBeVisible()
  })

  test('export stays pending until the job completes', async ({ page }) => {
    hold = 'export'
    await openApp(page, '/dashboard/review/9')
    const control = page.locator('[data-export-state]')
    await expect(control).toHaveText('Export XLSX')
    await control.click()
    await expect(control).toHaveText('Exporting')
    await expect(control).toHaveAttribute('data-export-state', 'pending')
    await expect(
      page.getByRole('button', { name: 'Dismiss Exported' })
    ).toHaveCount(0)
    exportResult = 'ok'
    release()
    await expect(
      page.getByRole('button', { name: 'Dismiss Exported' })
    ).toHaveCount(0)
    exportJobStatus = 'completed'
    await expect(
      page.getByRole('status').filter({ hasText: 'Exported' })
    ).toBeVisible()
    await expect(page.getByText('The file is ready to download.')).toBeVisible()
    await expect(
      page.getByRole('status').filter({ hasText: 'evidence-backed' })
    ).toHaveCount(0)
  })

  test('approve stays pending until the server accepts', async ({ page }) => {
    hold = 'approve'
    await openApp(page, '/dashboard/review/9')
    await page.getByRole('checkbox').last().check()
    const approve = page.locator('[data-approve-state]')
    await expect(approve).toHaveText('Approve')
    await approve.click()
    await expect(approve).toHaveText('Approving')
    await expect(approve).toHaveAttribute('data-approve-state', 'pending')
    await expect(
      page.getByRole('button', { name: 'Dismiss Approved' })
    ).toHaveCount(0)
    approveResult = 'ok'
    release()
    await expect(
      page.getByRole('status').filter({ hasText: 'Approved' })
    ).toBeVisible()
    await expect(
      page.getByText('The selected answers are marked approved.')
    ).toBeVisible()
  })

  test('an unsupported model is distinct and does not claim success', async ({
    page,
  }) => {
    generateResult = 'model'
    await openApp(page, '/dashboard/review/9')
    await page
      .locator('[data-microcopy="actions"]')
      .getByRole('button', { name: 'Generate', exact: true })
      .click()
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'Model not available' })
    await expect(alert).toBeVisible()
    await expect(
      alert.getByText(
        'That model is not available for this request. Choose a supported model and try again.'
      )
    ).toBeVisible()
    await expect(page.getByText('Unsupported model')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Dismiss Generated' })
    ).toHaveCount(0)
    await shoot(page, 'unsupported-model')
  })

  test('an unsupported file format is distinct and does not claim the file is stored', async ({
    page,
  }) => {
    uploadResult = 'format'
    await openApp(page, '/dashboard/documents')
    await page.locator('#doc-upload').setInputFiles({
      name: 'synthetic.exe',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('synthetic'),
    })
    await page
      .getByRole('dialog', { name: 'Upload Evidence Document' })
      .getByRole('button', { name: 'Upload', exact: true })
      .click()
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'File format not supported' })
    await expect(alert).toBeVisible()
    await expect(
      alert.getByText(
        'This file format is not supported. Choose a supported format and try again.'
      )
    ).toBeVisible()
    await expect(page.getByText('Allowed:')).toHaveCount(0)
    await expect(page.getByText(/corrupt/i)).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Dismiss Uploaded' })
    ).toHaveCount(0)
  })

  test('no supporting evidence is distinct from an abstention', async ({
    page,
  }) => {
    await openApp(page, '/dashboard/review/9')
    const evidence = page.locator('[data-outcome-code="no_evidence"]')
    await expect(evidence).toHaveText(
      'No eligible evidence was found for this item, so nothing was drafted. Add evidence that covers it, then try again.'
    )
    await expect(evidence).not.toContainText('model call')
    const abstained = page.locator('[data-outcome-code="model_abstained"]')
    await expect(abstained).toContainText('judged it insufficient to answer')
    await expect(abstained).not.toHaveText(await evidence.innerText())
  })

  test('a permission denial is distinct and does not echo the server detail', async ({
    page,
  }) => {
    approveResult = 'deny'
    await openApp(page, '/dashboard/review/9')
    await page.getByRole('checkbox').last().check()
    await page.getByRole('button', { name: 'Approve', exact: true }).click()
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'Action not available' })
    await expect(alert).toBeVisible()
    await expect(
      alert.getByText(
        'This account cannot complete that action. Ask someone who manages access for this workspace, then try again.'
      )
    ).toBeVisible()
    await expect(page.getByText(/insufficient permissions/i)).toHaveCount(0)
    await expect(page.getByText(/admin role/i)).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Dismiss Approved' })
    ).toHaveCount(0)
    await shoot(page, 'permission-denied')
  })

  test('keyboard reaches the action and dismisses the result', async ({
    page,
  }) => {
    generateResult = 'model'
    await openApp(page, '/dashboard/review/9')
    const generate = page
      .locator('[data-microcopy="actions"]')
      .getByRole('button', { name: 'Generate', exact: true })
    await generate.focus()
    const outline = await generate.evaluate(
      (el) => getComputedStyle(el).outlineStyle
    )
    expect(outline).not.toBe('none')
    await page.keyboard.press('Enter')
    const dismiss = page.getByRole('button', {
      name: 'Dismiss Model not available',
    })
    await expect(dismiss).toBeVisible()
    for (let i = 0; i < 80; i += 1) {
      if (
        await dismiss
          .evaluate((el) => el === document.activeElement)
          .catch(() => false)
      )
        break
      await page.keyboard.press('Tab')
    }
    await expect(dismiss).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(dismiss).toHaveCount(0)
  })

  test('action and message regions have no axe violations', async ({
    page,
  }) => {
    await openApp(page, '/dashboard/review/9')
    await expect(page.locator('[data-microcopy="actions"]')).toBeVisible()
    const themes = ['dark', 'light'] as const
    const widths = [360, 768, 1440] as const
    for (const theme of themes) {
      await page.evaluate((value) => {
        document.documentElement.setAttribute('data-theme', value)
      }, theme)
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 })
        await writeAxe(page, 'actions', theme, width)
      }
    }
  })
})
