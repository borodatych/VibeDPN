import { routes } from '@/generated/point0/routes'
import type { Page } from 'playwright'
import { expect } from 'playwright/test'

/**
 * Sign in as the box admin through the real form and wait for the session (the sign-out link in the header). The app runs
 * in a separate process, so the UI is the only honest way in. The password is the plain text behind `HTPASSWD_FILE` of
 * the test env (`E2E_BOX_PASSWORD`).
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
