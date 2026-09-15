import { baseStrings } from '@/modules/i18n/base'
import { loadCatalog } from '@/modules/i18n/catalog.server'
import { BASE_LANGUAGE, pickLanguage, placeholders, translate } from '@/modules/i18n/shared'
import { describe, expect, test } from 'bun:test'
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const LOCALES = join(import.meta.dir, '../../../locales')

const shipped = readdirSync(LOCALES)
  .filter((name) => name.endsWith('.json'))
  .map((name) => ({ name, strings: JSON.parse(readFileSync(join(LOCALES, name), 'utf8')) as Record<string, string> }))

describe('i18n catalog', () => {
  test('the base language is not shipped as a file: a seeded copy would freeze its wording', () => {
    expect(shipped.map((item) => item.name)).not.toContain(`${BASE_LANGUAGE}.json`)
    expect(shipped.length).toBeGreaterThan(0)
  })

  test.each(shipped)('$name has every key of the base and no other', ({ strings }) => {
    expect(Object.keys(strings).sort()).toEqual(Object.keys(baseStrings).sort())
  })

  test.each(shipped)('$name keeps the placeholders of every string', ({ strings }) => {
    for (const [key, text] of Object.entries(baseStrings)) {
      expect({ key, placeholders: placeholders(strings[key] ?? '') }).toEqual({
        key,
        placeholders: placeholders(text ?? ''),
      })
    }
  })

  test('placeholders are filled by name, a missing one stays visible', () => {
    expect(translate({ a: 'The LAN goes out through {uplink}' }, 'a', { uplink: 'vps' })).toBe(
      'The LAN goes out through vps',
    )
    expect(translate({ a: '{count} of {total}' }, 'a', { count: 2 })).toBe('2 of {total}')
    expect(translate({}, 'missing.key')).toBe('missing.key')
  })

  test('the browser choice wins, then the box default, then English; a language without its file never sticks', () => {
    expect(pickLanguage(['en', 'ru'], 'en', 'ru')).toBe('en')
    expect(pickLanguage(['en', 'ru'], undefined, 'ru')).toBe('ru')
    expect(pickLanguage(['en'], 'de', 'ru')).toBe('en')
  })

  test('a folder is read once into languages over the base; a broken file is skipped', () => {
    const dir = mkdtempSync(join(tmpdir(), 'vibedpn-locales-'))
    writeFileSync(join(dir, 'ru.json'), JSON.stringify({ 'nav.status': 'Статус', 'no.such.key': 'x', 'nav.rules': 7 }))
    writeFileSync(join(dir, 'de.json'), '{ not json')
    writeFileSync(join(dir, 'notes.txt'), 'ignored')
    const catalog = loadCatalog(dir)
    expect(catalog.languages).toEqual(['en', 'ru'])
    expect(catalog.strings.ru?.['nav.status']).toBe('Статус')
    expect(catalog.strings.ru?.['nav.rules']).toBe(baseStrings['nav.rules'])
    expect(catalog.strings.ru?.['no.such.key']).toBeUndefined()
    expect(loadCatalog(join(dir, 'missing')).languages).toEqual(['en'])
  })
})
