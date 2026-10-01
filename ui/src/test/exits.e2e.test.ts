import { routes } from '@/generated/point0/routes'
import { signedInPage } from '@/test/lib/e2e'
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

// The core of these tests is core/tests/panel_core.py: Tor in use, the masking exit and wg-proton on, DPN idle
describe('exits, notifications and the channels of the rules', () => {
  test('the exit in the URL is the one open, and a removed one falls back to the first that is on', async () => {
    await page.goto(`${routes.uplinks.abs()}?exit=wg-proton`)
    await expect(page.locator('[data-item="wg-proton"]')).toHaveAttribute('aria-current', 'true')
    await expect(page.getByRole('heading', { name: 'wg-proton' })).toBeVisible()
    await page.locator('[data-item="xray"]').click()
    await page.waitForURL('**/uplinks?exit=xray')
    await expect(page.getByText(/exit\.example\.org:443/)).toBeVisible()
    await page.goto(`${routes.uplinks.abs()}?exit=wg-gone`)
    await expect(page.locator('[data-item="tor"]')).toHaveAttribute('aria-current', 'true')
    expect(await sideScroll()).toBe(0)
  })

  test('the masking exit is a channel of a rule once it is on', async () => {
    await page.goto(routes.rules.abs())
    const site = page.getByRole('textbox', { name: /^(Сайт|Site)$/ })
    await site.fill('rutracker.org')
    await site.locator('xpath=..').getByRole('combobox').first().click()
    await page.getByRole('option', { name: /\(xray\)$/ }).click()
    await page.getByRole('button', { name: /^(Добавить правило|Add rule)$/ }).click()
    await expect(page.getByRole('row').filter({ hasText: 'rutracker.org' })).toContainText('xray')
  })

  test('smart mode is switched on the status page', async () => {
    await page.goto(routes.home.abs())
    const smart = page.getByRole('button', { name: /^(Умный — сайты по правилам|Smart — sites by the rules)$/ })
    await smart.click()
    await page.getByRole('button', { name: /^(Да|Yes)$/ }).click()
    // the mode of the box is the pressed button, and the box status names the sites of the rules
    await expect(smart).toBeDisabled()
    await expect(page.getByText(/^(Сайты по правилам|Sites by the rules)/)).toBeVisible()
  })

  test('the settings of the bot are saved from the header of their card', async () => {
    await page.goto(routes.notifications.abs())
    const after = page.getByRole('spinbutton')
    await after.fill('120')
    await page.getByRole('button', { name: /^(Сохранить|Save)$/ }).click()
    await expect(page.getByText(/^(Сохранено, действует сразу\.|Saved: it works at once\.)$/)).toBeVisible()
    await page.reload()
    await expect(page.getByRole('spinbutton')).toHaveValue('120')
  })

  test('the bridges of Tor are replaced on its card and given back to the built-in ones', async () => {
    await page.goto(`${routes.uplinks.abs()}?exit=tor`)
    await page.getByRole('button', { name: /^(Заменить мосты|Replace bridges)$/ }).click()
    const lines = page.getByRole('textbox', { name: /^(Строки мостов|Bridge lines)/ })
    const save = page.getByRole('button', { name: /^(Сохранить мосты|Save bridges)$/ })
    await lines.fill('webtunnel 203.0.113.9:443 url=https://bridge.example')
    await expect(page.getByText(/^(Строка 1: мосты webtunnel|Line 1: webtunnel bridges)/)).toBeVisible()
    await expect(save).toBeDisabled()
    // a line pasted from a torrc keeps its keyword; the rest of a private line never comes back
    await lines.fill('Bridge obfs4 203.0.113.9:443 ABCD cert=secret iat-mode=0')
    await save.click()
    await expect(page.getByText(/^(Свои мосты|Your own bridges): obfs4 203\.0\.113\.9:443$/)).toBeVisible()
    await expect(page.getByText(/cert=secret/)).toHaveCount(0)
    await page.getByRole('button', { name: /^(Вернуть встроенные|Back to built-in)$/ }).click()
    await page.getByRole('button', { name: /^(Да|Yes)$/ }).click()
    await expect(page.getByText(/^(Встроенные мосты Snowflake|Built-in Snowflake bridges)/)).toBeVisible()
  })

  test('a phone gets the exit under its own line, and no side scroll on either page', async () => {
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto(`${routes.uplinks.abs()}?exit=tor`)
    const heading = page.getByRole('heading', { name: /^(Бесплатный выход через Tor|Free exit through Tor)$/ })
    // the card lays out once the exits load: measured before that, it has no box yet
    await expect(heading).toBeVisible()
    const line = await page.locator('[data-item="tor"]').boundingBox()
    const card = await heading.boundingBox()
    const next = await page.locator('[data-item="xray"]').boundingBox()
    expect(line!.y < card!.y && card!.y < next!.y).toBe(true)
    expect(await sideScroll()).toBe(0)
    await page.goto(routes.notifications.abs())
    expect(await sideScroll()).toBe(0)
  })
})
