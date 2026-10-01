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

// The panel under test runs on this machine: anything else a page asks for is a third party
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]'])

/**
 * The requests panel pages made to a third party during this run, which the browser was not let through
 *
 * A box asks nothing of anyone outside it, so a test expects this empty
 *
 * @tags test, e2e
 * @related panelContext
 */
export const thirdPartyRequests: string[] = []

/**
 * A browser context for the panel: a request beyond this machine is cut off and recorded in `thirdPartyRequests`
 *
 * Cut, so a slow third party never holds a page, and recorded, so a test fails on it instead
 *
 * @tags test, e2e
 */
export const panelContext = async (
  browser: Browser,
  options: Parameters<Browser['newContext']>[0] = {},
): Promise<BrowserContext> => {
  const context = await browser.newContext(options)
  await context.route(
    (url) => !LOCAL_HOSTS.has(url.hostname),
    async (route) => {
      thirdPartyRequests.push(route.request().url())
      await route.abort()
    },
  )
  return context
}

let session: Promise<Awaited<ReturnType<BrowserContext['storageState']>>> | undefined

/**
 * A page of the panel already signed in, on its own context of the given size
 *
 * The box admin signs in once per run and every test file reuses that session: the panel limits sign-ins
 * (SIGN_IN_MAX_ATTEMPTS a window), and a sign-in per file runs into the limit as the files add up The sign-in itself is
 * the subject of the smoke test, which still goes through the form
 *
 * @tags test, e2e
 */
export const signedInPage = async (
  browser: Browser,
  viewport: { width: number; height: number },
  { password }: { password: string },
): Promise<Page> => {
  session ??= (async () => {
    const context = await panelContext(browser)
    await signInViaUi(await context.newPage(), { password })
    const state = await context.storageState()
    await context.close()
    return state
  })()
  const context = await panelContext(browser, { viewport, storageState: await session })
  return await context.newPage()
}
