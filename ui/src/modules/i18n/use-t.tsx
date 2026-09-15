import { XSelect } from '@/components/ui/select'
import { languageCookie, languageQuery } from '@/modules/i18n/api'
import { baseStrings, type T } from '@/modules/i18n/base'
import { BASE_LANGUAGE, translate } from '@/modules/i18n/shared'
import { useCallback } from 'react'

/**
 * The translator of the current language. Keys are typed by the base catalog: a key without a string does not compile.
 *
 * @tags i18n
 * @related languageQuery, translate
 */
export const useT = (): T => {
  const strings = languageQuery.useQuery().data?.strings ?? baseStrings
  return useCallback((key, params) => translate(strings, key, params), [strings])
}

/** The code of the current language (`ru`, `en`, …) for what formats by locale, like dates. */
export const useLanguage = (): string => languageQuery.useQuery().data?.language ?? BASE_LANGUAGE

/** The language switcher of the header; hidden while the box has a single language. */
export const LanguageSwitcher = () => {
  const data = languageQuery.useQuery().data
  if (!data || data.languages.length < 2) {
    return null
  }
  return (
    <XSelect
      options={data.languages.map((item) => ({ value: item.code, label: item.name }))}
      value={data.language}
      onValueChange={(value) => {
        languageCookie.set(String(value))
        void languageQuery.refetchQuery()
      }}
    />
  )
}
