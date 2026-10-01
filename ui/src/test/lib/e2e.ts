import { routes } from '@/generated/point0/routes'
import type { Browser, BrowserContext, Page } from 'playwright'
import { expect } from 'playwright/test'

/**
 * Sign in as the box admin through the real form and wait for the session (the sign-out link in the header). The app
 * runs in a separate process, so the UI is the only honest way in. The password is the plain text behind
 * `HTPASSWD_FILE` of the test env (`E2E_BOX_PASSWORD`).
 *
 * @tags test, e2e
 */
export const signInViaUi = async (page: Page, { password }: { password: string }) => {
  await page.goto(routes.signIn.abs())
  const form = page.locator('#sign-in-form')
  await form.locator('[name="password"]').fill(password)
  await form.locator('button[type="submit"]').click()
  await expect(page.locator(`a[href="${routes.signOut()}"]`)).toBeVisible()
}

let session: Promise<Awaited<ReturnType<BrowserContext['storageState']>>> | undefined

/**
 * A page of the panel already signed in, on its own context of the given size
 *
 * The box admin signs in once per run and every test file reuses that session: the panel limits sign-ins
 * (SIGN_IN_MAX_ATTEMPTS a window), and a sign-in per file runs into the limit as the files add up
 * The sign-in itself is the subject of the smoke test, which still goes through the form
 *
 * @tags test, e2e
 */
export const signedInPage = async (
  browser: Browser,
  viewport: { width: number; height: number },
  { password }: { password: string },
): Promise<Page> => {
  session ??= (async () => {
    const context = await browser.newContext()
    await signInViaUi(await context.newPage(), { password })
    const state = await context.storageState()
    await context.close()
    return state
  })()
  const context = await browser.newContext({ viewport, storageState: await session })
  return await context.newPage()
}
