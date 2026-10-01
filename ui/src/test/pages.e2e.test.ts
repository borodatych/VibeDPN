import { routes } from '@/generated/point0/routes'
import { panelContext, signedInPage } from '@/test/lib/e2e'
import { afterAll, beforeAll, describe, setDefaultTimeout, test } from 'bun:test'
import { chromium, type Browser, type Page } from 'playwright'
import { expect } from 'playwright/test'

setDefaultTimeout(30000)

let browser: Browser
let page: Page

// eslint-disable-next-line no-restricted-properties -- test-runner secret: the plain text behind the test htpasswd
const password = process.env.E2E_BOX_PASSWORD ?? ''

const sideScroll = async () => await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)

beforeAll(async () => {
  browser = await chromium.launch()
  page = await signedInPage(browser, { width: 1320, height: 900 }, { password })
})

afterAll(async () => {
  // awaited: a browser still closing when the file ends is killed by bun test, and the next file's pages hang
  await page.close()
  await browser.close()
})

// The core of these tests is core/tests/panel_core.py: a Wi-Fi box with devices, a journal, the access server on,
// an archive, two site rules and a network of Telegram
describe('rules, access, network, backup, devices and journal', () => {
  test('the section of «Rules» in the URL is the one open, and the list switches it', async () => {
    await page.goto(`${routes.rules.abs()}?section=networks`)
    await expect(page.locator('[data-item="networks"]')).toHaveAttribute('aria-current', 'true')
    await expect(page.getByRole('cell', { name: '149.154.160.0/20', exact: true })).toBeVisible()
    await page.locator('[data-item="lists"]').click()
    await page.waitForURL('**/rules?section=lists')
    await page.goto(`${routes.rules.abs()}?section=gone`)
    await expect(page.locator('[data-item="sites"]')).toHaveAttribute('aria-current', 'true')
  })

  test('a person added on «Access» gets a link at once', async () => {
    await page.goto(routes.access.abs())
    await page.getByRole('textbox', { name: /^(Имя человека|Name of the person)/ }).fill('anna')
    await page.getByRole('button', { name: /^(Добавить и показать ссылку|Add and show the link)$/ }).click()
    await expect(page.getByText(/^(Ссылка для anna|The link of anna)$/)).toBeVisible()
  })

  test('the Wi-Fi password is checked before it is sent', async () => {
    await page.goto(routes.network.abs())
    await page.getByRole('textbox', { name: /^(Новый пароль|New password)$/ }).fill('first-password')
    await page.getByRole('textbox', { name: /^(Ещё раз|Repeat it)$/ }).fill('second-password')
    await expect(page.getByText(/^(Пароли не совпадают\.|The two passwords differ\.)$/)).toBeVisible()
    await expect(page.getByRole('button', { name: /^(Сменить пароль|Change the password)$/ })).toBeDisabled()
  })

  test('a backup is asked from the header of the archives', async () => {
    await page.goto(routes.backup.abs())
    await page.getByRole('button', { name: /^(Сделать копию|Make a backup)$/ }).click()
    await page.getByRole('button', { name: /^(Да|Yes)$/ }).click()
    await expect(page.getByText(/^(Коробка делает копию\.|The box is making a backup\.)$/)).toBeVisible()
  })

  test('the node opens on its numbers: balance, earnings, sessions, traffic', async () => {
    await page.goto(routes.node.abs())
    const tiles = page.locator('[data-tile]')
    await expect(tiles).toHaveCount(4)
    await expect(tiles.first()).toContainText('0.12 MYST')
    await expect(tiles.nth(2)).toContainText('14')
  })

  test('signed out, the header shows no pages: the form is all there is to do', async () => {
    const stranger = await (await panelContext(browser, { viewport: { width: 1320, height: 900 } })).newPage()
    await stranger.goto(routes.signIn.abs())
    await expect(stranger.locator('#sign-in-form')).toBeVisible()
    await expect(stranger.locator('header nav')).toHaveCount(0)
    await expect(stranger.getByRole('button', { name: /^(Ещё|More)$/ })).toHaveCount(0)
    await stranger.close()
  })

  test('on a phone the devices and the journal are cards, and no page scrolls sideways', async () => {
    await page.setViewportSize({ width: 375, height: 800 })
    for (const route of [routes.devices, routes.journal]) {
      await page.goto(route.abs())
      await expect(page.locator('thead')).toBeHidden()
      // every row a framed card, the last one too: the table of the pack takes the border off the last row
      const rows = await page
        .locator('tbody tr')
        .evaluateAll((all) => all.map((row) => [getComputedStyle(row).display, getComputedStyle(row).borderTopWidth]))
      expect(rows.length).toBeGreaterThan(1)
      expect(rows.every(([display, border]) => display === 'grid' && border === '1px')).toBe(true)
    }
    for (const route of [routes.rules, routes.access, routes.network, routes.backup, routes.devices, routes.journal]) {
      await page.goto(route.abs())
      await expect(page.locator('h1')).toBeVisible()
      expect(await sideScroll()).toBe(0)
    }
  })
})
