import { logger } from '@/lib/logger'
import { baseStrings } from '@/modules/i18n/base'
import { BASE_LANGUAGE, LANGUAGE_CODE, knownStrings, type Strings } from '@/modules/i18n/shared'
import '@point0/core/server-only'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

export type Catalog = {
  /** every language with a file, and English, sorted */
  languages: string[]
  /** language → its strings laid over the base */
  strings: Partial<Record<string, Strings>>
}

const FILE = /^([a-z]{2})\.json$/

/**
 * Read the language files of `dir` once: a file that cannot be read or parsed is skipped with a log line, the panel
 * keeps talking. A missing directory leaves English only.
 */
export const loadCatalog = (dir: string | undefined): Catalog => {
  const strings: Partial<Record<string, Strings>> = { [BASE_LANGUAGE]: baseStrings }
  let names: string[]
  try {
    names = dir ? readdirSync(dir) : []
  } catch {
    names = []
  }
  for (const name of names) {
    const code = FILE.exec(name)?.[1]
    if (!code || !LANGUAGE_CODE.test(code)) {
      continue
    }
    try {
      const raw: unknown = JSON.parse(readFileSync(join(dir ?? '', name), 'utf8'))
      strings[code] = { ...baseStrings, ...knownStrings(baseStrings, raw) }
    } catch (error) {
      logger.log({ level: 'warn', category: 'i18n', input: `cannot read language file ${name}`, props: { error } })
    }
  }
  return { languages: Object.keys(strings).sort(), strings }
}

let catalog: Catalog | undefined

/**
 * The catalog of the box, read at the first request and kept in memory: removing files under a running panel breaks
 * nothing.
 *
 * @tags i18n
 * @related loadCatalog, languageQuery
 */
export const getCatalog = (dir: string | undefined): Catalog => {
  catalog ??= loadCatalog(dir)
  return catalog
}
