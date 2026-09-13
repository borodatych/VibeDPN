import { CookieStore } from '@point0/core/cookie-store'
import { useHead } from '@unhead/react'
import { Moon, Sun, SunMoon } from 'lucide-react'
import { useMemo } from 'react'
import { Button } from './button'

type ColorScheme = 'dark' | 'light'
type ColorMode = 'dark' | 'light' | 'system'

export const colorModeCookie = CookieStore.define<ColorMode>('color-mode')

const normalizeMode = (mode: string | undefined): ColorMode => {
  if (mode === 'light' || mode === 'dark') {
    return mode as ColorScheme
  }
  return 'system'
}

const normalizeScheme = (mode: ColorMode): ColorScheme | undefined => {
  if (mode === 'light' || mode === 'dark') {
    return mode as ColorScheme
  }
  if (typeof window === 'undefined') {
    return undefined
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useTheme = (): { scheme: ColorScheme | undefined; mode: ColorMode } => {
  const mode = normalizeMode(colorModeCookie.use())
  return useMemo(() => {
    return {
      scheme: normalizeScheme(mode),
      mode,
    }
  }, [mode])
}

export const setTheme = (mode: ColorMode) => {
  colorModeCookie.set(mode)
}

export const getColorMode = () => {
  return normalizeMode(colorModeCookie.get())
}

export const getColorScheme = () => {
  return normalizeScheme(getColorMode())
}

export const getTheme = () => {
  const mode = getColorMode()
  return {
    scheme: normalizeScheme(mode),
    mode,
  }
}

export const ThemeProvider = () => {
  const { scheme } = useTheme()
  useHead({
    htmlAttrs: {
      class: {
        dark: scheme === 'dark',
        light: scheme === 'light',
      },
    },
  })
  return null
}

export const useThemeSwitcher = () => {
  const { mode } = useTheme()
  const nextMode = mode === 'dark' ? 'light' : mode === 'light' ? 'system' : 'dark'
  const Icon = mode === 'dark' ? Moon : mode === 'light' ? Sun : SunMoon
  const modeName = mode.charAt(0).toUpperCase() + mode.slice(1)
  const nextModeName = nextMode.charAt(0).toUpperCase() + nextMode.slice(1)
  const hint = `Current theme: ${modeName}, switch to ${nextModeName}`

  return {
    Icon,
    nextMode,
    nextModeName,
    mode,
    modeName,
    hint,
    setNextTheme: () => setTheme(nextMode),
  }
}

export const ThemeSwitcher = ({
  className,
  compact = false,
  size = 'default',
  variant = 'secondary',
  children,
}: {
  className?: string
  compact?: boolean
  size?: 'lg' | 'default' | 'sm'
  variant?: React.ComponentProps<typeof Button>['variant']
  children?: (props: ReturnType<typeof useThemeSwitcher>) => Exclude<React.ReactNode, Promise<any>>
}) => {
  const state = useThemeSwitcher()

  if (children) {
    return children(state)
  }

  const { Icon, modeName, hint, setNextTheme } = state

  return (
    <Button
      icon={Icon}
      size={compact ? `icon-${size}` : size}
      variant={variant}
      onClick={setNextTheme}
      className={className}
      hint={compact ? hint : undefined}
    >
      {compact ? null : modeName}
    </Button>
  )
}
