import { useIsMobile } from '@/components/hooks/use-mobile'
import { navigate } from '@/lib/navigation'
import { toBetterAuthMessageIfSuitable } from '@/modules/auth/error'
import { stringify } from '@1gr14/flat'
import { useLocation } from '@point0/core/navigation'
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from 'lucide-react'
import { useEffect } from 'react'
import { Toaster as Sonner, toast, type ToasterProps } from 'sonner'

const Toaster = ({ ...props }: ToasterProps) => {
  const isMobile = useIsMobile()
  return (
    <Sonner
      // This app does not use `next-themes` ThemeProvider. We keep Sonner in "system" mode.
      theme={'light' as ToasterProps['theme']}
      // On a wide screen a toast belongs out of the way, in the bottom right corner. On a narrow one it goes back to
      // the top, where Sonner stretches it across the width — starting below the sticky header (`h-16`) so it never
      // covers the logo or the burger. `useIsMobile` is false until it has measured, so the server and the first client
      // render agree on the desktop position; there is no toast on screen yet to see it change.
      position={isMobile ? 'top-center' : 'bottom-right'}
      // `offset` is the wide-screen one; it only shows in the narrow band where the toast is already at the top but
      // Sonner does not consider the viewport mobile yet (>600px).
      offset={{ top: '80px', right: '24px', bottom: '24px', left: '24px' }}
      mobileOffset={{ top: '80px', right: '16px', bottom: '16px', left: '16px' }}
      // Make `toast.error/success/...` visually distinct (red/green/etc) instead of "normal" toasts.
      richColors
      // eslint-disable-next-line tailwindcss/no-custom-classname -- `toaster` is Sonner's own class
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
          // Variant colors (used when `richColors` is enabled)
          '--error-bg': 'color-mix(in oklch, var(--destructive) 10%, var(--popover))',
          // No border for error toasts, background tint is enough.
          // '--error-border': 'transparent',
          '--error-border': 'color-mix(in oklch, var(--destructive) 50%, var(--popover))',
          '--error-text': 'var(--destructive)',
          '--border-radius': 'var(--radius)',
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: 'cn-toast shadow-none',
        },
      }}
      {...props}
    />
  )
}

const SearchParamsToast = () => {
  const { search, pathname } = useLocation()
  const { error, success, ...restSearch } = search

  useEffect(() => {
    if (typeof error === 'string' && error.length > 0) {
      const fixedMessage = toBetterAuthMessageIfSuitable(error)
      toast.error(fixedMessage)
      void navigate.to([pathname, stringify(restSearch)].filter(Boolean).join('?'), { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error])

  useEffect(() => {
    if (!error && typeof success === 'string' && success.length > 0) {
      toast.success(success)
      void navigate.to([pathname, stringify(restSearch)].filter(Boolean).join('?'), { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [success, error])

  return null
}

export { SearchParamsToast, Toaster }
