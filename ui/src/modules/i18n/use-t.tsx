import { baseStrings, type T } from '@/modules/i18n/base'
import { BASE_LANGUAGE, type Strings, translate } from '@/modules/i18n/shared'
import { createContext, useCallback, useContext } from 'react'

/** The language the panel speaks now and its strings, merged over the base on the server. */
export type LanguageState = { language: string; strings: Strings }

/**
 * The current language, handed down by `LanguageProvider`
 *
 * No query lives here: `lib/root` imports the error pages, and they import this module
 *
 * A point built from `root` in this graph would read `root` before it exists — a cycle of ES modules
 *
 * Outside the provider — an error boundary above the app, a test — the panel speaks the base language
 *
 * @tags i18n, rule
 * @related LanguageProvider, languageQuery
 */
export const LanguageContext = createContext<LanguageState>({ language: BASE_LANGUAGE, strings: baseStrings })

/**
 * The translator of the current language. Keys are typed by the base catalog: a key without a string does not compile.
 *
 * @tags i18n
 * @related LanguageContext, translate
 */
export const useT = (): T => {
  const { strings } = useContext(LanguageContext)
  return useCallback((key, params) => translate(strings, key, params), [strings])
}

/** The code of the current language (`ru`, `en`, …) for what formats by locale, like dates. */
export const useLanguage = (): string => useContext(LanguageContext).language
