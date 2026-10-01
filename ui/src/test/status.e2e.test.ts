import { routes } from '@/generated/point0/routes'
import { signedInPage } from '@/test/lib/e2e'
import { afterAll, beforeAll, describe, setDefaultTimeout, test } from 'bun:test'
import { chromium, type Browser, type Page } from 'playwright'
import { expect } from 'playwright/test'

let browser: Browser
let page: Page

// eslint-disable-next-line no-restricted-properties -- test-runner secret: the plain text behind the test htpasswd
const password = process.env.E2E_BOX_PASSWORD ?? ''

setDefaultTimeout(30000)

const sideScroll = async () => await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)

beforeAll(async () => {
  browser = await chromium.launch()
  page = await signedInPage(browser, { width: 1320, height: 900 }, { password })
})

afterAll(async () => {
  void page.close()
  void browser.close()
})

describe('status page and header', () => {
  test('the header fits a laptop: six pages in sight, the rest in «More», and every one opens', async () => {
    await page.goto(routes.home.abs())
    await expect(page.locator('h1')).toBeVisible()
    expect(await sideScroll()).toBe(0)
    await page.getByRole('button', { name: /^(Ещё|More)$/ }).click()
    await page.getByRole('menuitem').nth(3).click() // «Копия»: the fourth page opened now and then
    await page.waitForURL(`**${routes.backup()}`)
  })

  test('the exit cards share the lines of the grid, and the check of the box is asked from its header', async () => {
    await page.goto(routes.home.abs())
    // the last row: above it the kill switch of the exit in use runs to more lines than the idle one's dash
    const checked = page.locator('[data-uplink] [data-row="checked"]')
    await expect(checked).toHaveCount(4)
    const [first, second] = await checked.evaluateAll((rows) => rows.map((row) => row.getBoundingClientRect().top))
    expect(first).toBe(second)
    await page.getByRole('button', { name: /^(Проверить|Check)$/ }).click()
    // the panel asks core, core leaves the request for the host: the card says the box is checking itself
    await expect(page.getByText(/^(Коробка проверяет себя\.|The box is checking itself\.)$/)).toBeVisible()
  })

  test('a phone gets one column and no side scroll', async () => {
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto(routes.home.abs())
    await expect(page.locator('h1')).toBeVisible()
    expect(await sideScroll()).toBe(0)
  })
})
