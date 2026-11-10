import { expect, test } from '@playwright/test'

const generic =
  'If that email is waiting for verification, a new message is on the way.'

async function hideProviders(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/oauth/providers', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        google: false,
        github: false,
        microsoft: false,
        sso: false,
        idme: false,
      }),
    })
  )
}

test('login offers a new verification email and shows the generic reply', async ({
  page,
}) => {
  await hideProviders(page)
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Verify your email before signing in.',
        error: {
          code: 'email_not_verified',
          message: 'Verify your email before signing in.',
          retryable: false,
        },
      }),
    })
  )
  let posted = ''
  await page.route('**/api/auth/resend-verification', async (route) => {
    posted = route.request().postData() || ''
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: generic }),
    })
  })
  await page.goto('/login')
  await page.getByLabel('Email').fill('person@example.com')
  await page.getByLabel('Password').fill('example-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page
    .getByRole('button', { name: 'Send a new verification email' })
    .click()
  await expect(page.getByText(generic)).toBeVisible()
  expect(posted).toContain('person@example.com')
  await expect(
    page.getByRole('link', { name: 'Enter your verification code' })
  ).toBeVisible()
})

test('login explains when another verification email is rate limited', async ({
  page,
}) => {
  await hideProviders(page)
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'Verify your email before signing in.',
        error: { code: 'email_not_verified' },
      }),
    })
  )
  await page.route('**/api/auth/resend-verification', (route) =>
    route.fulfill({
      status: 429,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Too many requests. Try again later.' }),
    })
  )
  await page.goto('/login')
  await page.getByLabel('Email').fill('person@example.com')
  await page.getByLabel('Password').fill('example-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page
    .getByRole('button', { name: 'Send a new verification email' })
    .click()
  await expect(
    page.getByText('Too many verification emails. Try again later.')
  ).toBeVisible()
})

test('register success can send another verification email', async ({
  page,
}) => {
  await page.route('**/api/auth/register', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        message:
          'If that email is not yet registered, you will receive a verification code.',
      }),
    })
  )
  await page.route('**/api/auth/resend-verification', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: generic }),
    })
  )
  await page.goto('/register')
  await page.getByLabel('Email').fill('person@example.com')
  await page.getByLabel('Password').fill('example-password')
  await page.getByRole('button', { name: 'Register' }).click()
  await page
    .getByRole('button', { name: 'Send a new verification email' })
    .click()
  await expect(page.getByText(generic)).toBeVisible()
})

test('verify-email accepts a 6-digit code for the typed address', async ({
  page,
}) => {
  let posted = ''
  await page.route('**/api/auth/verify-code', async (route) => {
    posted = route.request().postData() || ''
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Email verified.' }),
    })
  })
  await page.goto('/verify-email')
  await page.getByLabel('Email').fill('person@example.com')
  await page.getByLabel('Verification code').fill('123456')
  await page.getByRole('button', { name: 'Verify code' }).click()
  await expect(page.getByText('Email verified.')).toBeVisible()
  expect(posted).toContain('person@example.com')
  expect(posted).toContain('123456')
})
