/**
 * The panel catalog: flat dotted keys, named placeholders. English is the base built into the bundle; every other
 * language is a file `<code>.json` of the box (docs/manuals/languageFileSpec.md), laid over the base, so a half
 * translated file still shows every string.
 *
 * No decision in the panel is made by the text of a string: pure modules return keys and data, the screen builds the
 * phrase.
 *
 * @tags rule, i18n
 * @related translate, useT, getCatalog
 */
// Partial: a lookup of a key the catalog does not have is undefined at run time, and the type says so.
export type Strings = Partial<Record<string, string>>

export const BASE_LANGUAGE = 'en'
export const LANGUAGE_CODE = /^[a-z]{2}$/
/** The key a language file names itself with, shown in the language switcher. */
export const LANGUAGE_NAME_KEY = 'language.name'
/**
 * Keys of a language file that are core's, not the panel's: the messages of the Telegram bot. The panel ignores them;
 * core's gate checks them (core/tests/test_core_i18n.py).
 */
export const CORE_KEY_PREFIX = 'bot.'

const PLACEHOLDER = /\{(\w+)\}/g

export type Params = Record<string, string | number>

/** The string of a key with its placeholders filled; a key without a string or a missing value stays visible. */
export const translate = (strings: Strings, key: string, params?: Params): string =>
  (strings[key] ?? key).replace(PLACEHOLDER, (whole, name: string) =>
    params && name in params ? String(params[name]) : whole,
  )

/** The placeholder names of a string, sorted: a translation keeps the same set. */
export const placeholders = (text: string): string[] =>
  [...new Set([...text.matchAll(PLACEHOLDER)].map(([, name]) => name))].sort()

/** Only string values of known keys: anything else in a language file is ignored, never shown. */
export const knownStrings = (base: Strings, raw: unknown): Strings => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }
  const result: Strings = {}
  for (const [key, value] of Object.entries(raw)) {
    if (key in base && typeof value === 'string') {
      result[key] = value
    }
  }
  return result
}

/**
 * The language a request gets: the browser's choice, then the box default (`ui.language`), then English — each only
 * when its file is there, so a removed language never sticks.
 */
export const pickLanguage = (available: readonly string[], ...wanted: (string | undefined)[]): string =>
  wanted.find((code): code is string => !!code && available.includes(code)) ?? BASE_LANGUAGE
