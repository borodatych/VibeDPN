import { XSelect } from '@/components/ui/select'
import { languageCookie, languageQuery } from '@/modules/i18n/api'
import { baseStrings } from '@/modules/i18n/base'
import { BASE_LANGUAGE } from '@/modules/i18n/shared'
import { LanguageContext, type LanguageState } from '@/modules/i18n/use-t'
import { type ReactNode, useMemo } from 'react'

/**
 * The one reader of `languageQuery`: everything below it speaks the language it loaded
 *
 * It sits in `App` under the query client, so the server renders the page in that language too
 *
 * @tags i18n
 * @related LanguageContext, languageQuery
 */
export const LanguageProvider = ({ children }: { children: ReactNode }) => {
  const data = languageQuery.useQuery().data
  const value = useMemo<LanguageState>(
    () => ({ language: data?.language ?? BASE_LANGUAGE, strings: data?.strings ?? baseStrings }),
    [data],
  )
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

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
