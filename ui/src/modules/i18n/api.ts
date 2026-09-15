import { root } from '@/lib/root'
import { serverEnv } from '@/modules/env/server'
import { getCatalog } from '@/modules/i18n/catalog.server'
import { LANGUAGE_NAME_KEY, pickLanguage } from '@/modules/i18n/shared'
import { CookieStore } from '@point0/core/cookie-store'

/** The language the owner picked in this browser; without it the box default (`ui.language`) applies. */
export const languageCookie = CookieStore.define<string>('language')

/**
 * The strings of the current language, merged over the base once on the server: the client never merges catalogs.
 *
 * @tags i18n, query
 * @related useT, getCatalog
 */
export const languageQuery = root.lets
  .query()
  .loader(() => {
    const catalog = getCatalog(serverEnv.LOCALES_DIR)
    const language = pickLanguage(catalog.languages, languageCookie.get(), serverEnv.UI_LANGUAGE)
    return {
      language,
      languages: catalog.languages.map((code) => ({
        code,
        name: catalog.strings[code]?.[LANGUAGE_NAME_KEY] ?? code,
      })),
      strings: catalog.strings[language] ?? {},
    }
  })
  .query({ staleTime: Infinity })
