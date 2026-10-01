import { FONTS_ROUTE } from '@/lib/fonts'
import { FONT_STYLESHEETS, panelFonts } from '@/lib/fonts.build'
import { describe, expect, it } from 'bun:test'
import { existsSync } from 'node:fs'
import path from 'node:path'

describe('panelFonts', () => {
  const { css, directories } = panelFonts(import.meta.dir)
  const urls = [...css.matchAll(/url\(([^)]+)\)/g)].map((match) => match[1]!)

  it('declares every face of every stylesheet', () => {
    expect(css.match(/@font-face/g)?.length).toBeGreaterThanOrEqual(FONT_STYLESHEETS.length)
  })

  // A url left relative or pointing elsewhere would send the browser to a third party or to a 404
  it('points every url at a file the panel serves', () => {
    const missing = urls.filter((url) => {
      const route = Object.keys(directories).find((item) => url.startsWith(`/${item}/`))
      return !route || !existsSync(path.join(directories[route]!, url.slice(route.length + 2)))
    })
    expect(urls.length).toBeGreaterThan(0)
    expect(missing).toEqual([])
  })

  it('serves the files under its own route', () => {
    expect(Object.keys(directories).every((route) => route.startsWith(`${FONTS_ROUTE}/`))).toBe(true)
  })
})
