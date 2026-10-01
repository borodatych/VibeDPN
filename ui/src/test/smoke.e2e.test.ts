import { routes } from '@/generated/point0/routes'
import { panelContext, signInViaUi, thirdPartyRequests } from '@/test/lib/e2e'
import { afterAll, beforeAll, describe, test } from 'bun:test'
import { chromium, type Browser, type Page } from 'playwright'
import { expect } from 'playwright/test'

let browser: Browser
let page: Page

// eslint-disable-next-line no-restricted-properties -- test-runner secret: the plain text behind the test htpasswd
const password = process.env.E2E_BOX_PASSWORD ?? ''

beforeAll(async () => {
  browser = await chromium.launch()
  page = await (await panelContext(browser)).newPage()
})

afterAll(async () => {
  void page.close()
  void browser.close()
})

describe('smoke e2e', () => {
  test('an anonymous visitor gets the sign-in form instead of the panel', async () => {
    await page.goto(routes.home.abs())
    await expect(page.locator('#sign-in-form')).toBeVisible()
  })

  test('the box password opens the panel', async () => {
    await signInViaUi(page, { password })
    await page.goto(routes.home.abs())
    await expect(page.locator('h1')).toHaveText(/^(Состояние коробки|Box status)$/)
  })

  // A visit to the panel is nobody else's business, and a slow third party would hold the page
  test('the panel loads nothing from outside the box', async () => {
    await page.goto(routes.home.abs(), { waitUntil: 'load' })
    await expect(page.locator('h1')).toBeVisible()
    expect(thirdPartyRequests).toEqual([])
  })
})
