import { CookieStore } from '@point0/core/cookie-store'
import { useHead } from '@unhead/react'
import { Palette } from 'lucide-react'
import { Button } from './button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from './dropdown-menu'
import { useT } from '@/modules/i18n/use-t'

/**
 * The panel palette, kept per device — a cookie, not a database row: the phone in the sun and the laptop in the
 * evening may well want different palettes, exactly like the light/dark mode next to it
 *
 * The same mechanism as in VibeSter, which the palettes come from (styles/palettes.css): a Point0 CookieStore, so SSR
 * renders the right colors without a flash, and a useHead attribute on <html>
 * The palettes override the --light-* / --dark-* pairs, which keeps the light/dark switch working on top of any of them
 */

export const PALETTE_FAMILIES = ['warm', 'neutral'] as const

export type PaletteFamily = (typeof PALETTE_FAMILIES)[number]

/**
 * The swatch shows the DARK half of a palette: [background, accent, a second visible color]
 * The light half would be three almost white dots, by which the palettes cannot be told apart
 */
export const PALETTES = [
  { id: 'terracotta', family: 'warm', swatch: ['#1c1714', '#c46f4e', '#93a87d'] },
  { id: 'espresso', family: 'warm', swatch: ['#171310', '#c98d5c', '#8aa87c'] },
  { id: 'honey', family: 'warm', swatch: ['#191512', '#c99b47', '#9aa87a'] },
  { id: 'tobacco', family: 'warm', swatch: ['#16130f', '#ab8d5f', '#8a9878'] },
  { id: 'stock', family: 'warm', swatch: ['#18181b', '#5b6bd5', '#4ade80'] },
  { id: 'ide-light', family: 'neutral', swatch: ['#1c1c1c', '#4daafc', '#3fb950'] },
  { id: 'ide-slate', family: 'neutral', swatch: ['#1f1f1f', '#0078d4', '#3fb950'] },
  { id: 'graphite', family: 'neutral', swatch: ['#1f2123', '#4a6d8c', '#7fb3d5'] },
  { id: 'midnight', family: 'neutral', swatch: ['#171923', '#4a6fb5', '#7dcfff'] },
] as const satisfies readonly { id: string; family: PaletteFamily; swatch: readonly string[] }[]

export type PaletteId = (typeof PALETTES)[number]['id']

/** The default of VibeSter; `stock` is kept only as an explicit choice, never the fallback */
export const DEFAULT_PALETTE: PaletteId = 'terracotta'

export const paletteCookie = CookieStore.define<PaletteId>('palette')

/**
 * A known palette, or the default for a missing or stale cookie
 *
 * @tags palette
 */
export const normalizePalette = (value: string | undefined): PaletteId =>
  PALETTES.some((palette) => palette.id === value) ? (value as PaletteId) : DEFAULT_PALETTE

export const usePalette = (): PaletteId => normalizePalette(paletteCookie.use())

export const PaletteProvider = () => {
  const palette = usePalette()
  useHead({
    htmlAttrs: {
      // `stock` removes the attribute: the boilerplate theme is the absence of an override
      'data-palette': palette === 'stock' ? undefined : palette,
    },
  })
  return null
}

const Swatch = ({ colors }: { colors: readonly string[] }) => (
  <span className="flex items-center gap-1">
    {colors.map((color) => (
      <span
        key={color}
        className="inline-block size-3 rounded-full border border-border"
        style={{ backgroundColor: color }}
      />
    ))}
  </span>
)

/**
 * The palette menu of the header, next to the light/dark switch, grouped by family
 *
 * @tags palette
 */
export const PaletteSwitcher = () => {
  const t = useT()
  const palette = usePalette()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" size="icon-default" icon={Palette} aria-label={t('palette.menu')} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto min-w-56">
        <DropdownMenuRadioGroup value={palette} onValueChange={(value) => paletteCookie.set(normalizePalette(value))}>
          {PALETTE_FAMILIES.map((family) => (
            <DropdownMenuGroup key={family}>
              <DropdownMenuLabel>{t(`palette.family.${family}`)}</DropdownMenuLabel>
              {PALETTES.filter((option) => option.family === family).map((option) => (
                <DropdownMenuRadioItem key={option.id} value={option.id} className="gap-2 whitespace-nowrap">
                  <Swatch colors={option.swatch} />
                  {t(`palette.${option.id}`)}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuGroup>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
