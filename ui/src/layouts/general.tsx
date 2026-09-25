import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer'
import { ThemeSwitcher } from '@/components/ui/theme'
import { routes } from '@/generated/point0/routes'
import { NavLink } from '@/lib/navigation'
import { root } from '@/lib/root'
import { getMeQuery } from '@/modules/auth/api'
import type { Me } from '@/modules/auth/server'
import type { T } from '@/modules/i18n/base'
import { languageQuery } from '@/modules/i18n/api'
import { LanguageSwitcher } from '@/modules/i18n/provider'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { useHead } from '@unhead/react'
import { cn } from '@/utils'
import { Menu, X } from 'lucide-react'
import { type ComponentProps, useState } from 'react'

type NavItem = { label: string; to: string }

// Left of the header — your top-level pages.
const navLinks = (t: T): NavItem[] => [
  { label: t('nav.status'), to: routes.home() },
  { label: t('nav.devices'), to: routes.devices() },
  { label: t('nav.rules'), to: routes.rules() },
  { label: t('nav.node'), to: routes.node() },
  { label: t('nav.network'), to: routes.network() },
  { label: t('nav.uplinks'), to: routes.uplinks() },
  { label: t('nav.access'), to: routes.access() },
  { label: t('nav.notifications'), to: routes.notifications() },
  { label: t('nav.journal'), to: routes.journal() },
]

// Right of the header — depends on who's signed in.
const accountLinks = (me: Me | null | undefined, t: T): NavItem[] =>
  !me ? [{ label: t('nav.signIn'), to: routes.signIn() }] : [{ label: t('nav.signOut'), to: routes.signOut() }]

const navLinkClassName = ({ exact }: { exact: boolean }) =>
  cn(
    'font-accent text-sm text-muted-foreground transition-colors hover:text-foreground',
    exact && 'pointer-events-none font-semibold text-foreground',
  )

const mobileLinkClassName = 'rounded-md px-3 py-2 font-accent text-sm text-foreground hover:bg-muted'

const NavItems = ({
  links,
  className = navLinkClassName,
  onNavigate,
}: {
  links: NavItem[]
  className?: ComponentProps<typeof NavLink>['className']
  onNavigate?: () => void
}) =>
  links.map((link) => (
    <NavLink key={link.label} to={link.to} className={className} onClick={onNavigate}>
      {link.label}
    </NavLink>
  ))

export const generalLayout = root.lets
  .layout()
  .with(languageQuery)
  .layout(({ children }) => {
    const me = getMeQuery.useQuery().data?.me
    const t = useT()
    useHead({ htmlAttrs: { lang: useLanguage() } })
    const [menuOpen, setMenuOpen] = useState(false)

    return (
      <div className="flex min-h-dvh w-full flex-col">
        <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
          <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
            <div className="flex items-center gap-8">
              <NavLink
                to={routes.home()}
                className={{
                  default: 'font-logo text-lg font-bold text-foreground hover:text-link-hover',
                  exact: 'pointer-events-none',
                }}
              >
                VibeDPN
              </NavLink>
              <nav className="hidden items-center gap-6 md:flex">
                <NavItems links={navLinks(t)} />
              </nav>
            </div>

            <div className="hidden items-center gap-6 md:flex">
              <nav className="flex items-center gap-6">
                <NavItems links={accountLinks(me, t)} />
              </nav>
              <LanguageSwitcher />
              <ThemeSwitcher compact />
            </div>

            <div className="flex items-center gap-1 md:hidden">
              <LanguageSwitcher />
              <ThemeSwitcher compact />
              <Drawer open={menuOpen} onOpenChange={setMenuOpen} direction="right">
                <DrawerTrigger asChild>
                  <Button variant="ghost" size="icon-default" aria-label={t('nav.openMenu')} icon={Menu} />
                </DrawerTrigger>
                <DrawerContent className="w-[80vw] max-w-xs text-foreground">
                  <DrawerTitle className="sr-only">{t('nav.menu')}</DrawerTitle>
                  <DrawerDescription className="sr-only">{t('nav.primary')}</DrawerDescription>
                  <div className="flex flex-col gap-1 p-4">
                    <DrawerClose asChild className="mb-2 self-end">
                      <Button variant="ghost" size="icon-default" aria-label={t('nav.closeMenu')} icon={X} />
                    </DrawerClose>
                    <NavItems
                      links={navLinks(t)}
                      className={mobileLinkClassName}
                      onNavigate={() => setMenuOpen(false)}
                    />
                    <div className="my-2 h-px bg-border" />
                    <NavItems
                      links={accountLinks(me, t)}
                      className={mobileLinkClassName}
                      onNavigate={() => setMenuOpen(false)}
                    />
                  </div>
                </DrawerContent>
              </Drawer>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 lg:py-12" data-layout-content>
          {children}
        </main>
      </div>
    )
  })
