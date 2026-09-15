import { baseStrings, type T } from '@/modules/i18n/base'
import { translate } from '@/modules/i18n/shared'

/** The English translator, for tests and anything outside a render. */
export const baseT: T = (key, params) => translate(baseStrings, key, params)
