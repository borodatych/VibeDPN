import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { PaletteSwitcher } from '@/components/ui/palette'
import { ThemeSwitcher } from '@/components/ui/theme'
import { routes } from '@/generated/point0/routes'
import { NavLink } from '@/lib/navigation'
import { root } from '@/lib/root'
import { boxRoleQuery } from '@/features/box/api'
import { navOfRole, type pagesOfRole } from '@/features/box/shared'
import { getMeQuery } from '@/modules/auth/api'
import type { Me } from '@/modules/auth/server'
import type { T } from '@/modules/i18n/base'
import { languageQuery } from '@/modules/i18n/api'
import { LanguageSwitcher } from '@/modules/i18n/provider'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { useLocation } from '@point0/core/navigation'
import { useHead } from '@unhead/react'
import { cn } from '@/utils'
import { ChevronDown, Menu, X } from 'lucide-react'
import { type ComponentProps, useState } from 'react'

type NavItem = { label: string; to: string }

// Left of the header — the top-level pages of the role of this box.
const pageLinks = (t: T): Record<PageName, NavItem> => ({
  home: { label: t('nav.status'), to: routes.home() },
  devices: { label: t('nav.devices'), to: routes.devices() },
  rules: { label: t('nav.rules'), to: routes.rules() },
  node: { label: t('nav.node'), to: routes.node() },
  network: { label: t('nav.network'), to: routes.network() },
  uplinks: { label: t('nav.uplinks'), to: routes.uplinks() },
  peers: { label: t('nav.peers'), to: routes.peers() },
  access: { label: t('nav.access'), to: routes.access() },
  notifications: { label: t('nav.notifications'), to: routes.notifications() },
  journal: { label: t('nav.journal'), to: routes.journal() },
  backup: { label: t('nav.backup'), to: routes.backup() },
})

type PageName = ReturnType<typeof pagesOfRole>[number]

type NavLinks = { main: NavItem[]; more: NavItem[] }

/** The pages of the header: in sight, and in the menu «Ещё» with the password of the panel when signed in */
const navLinks = (t: T, role: string | null | undefined, signedIn: boolean): NavLinks => {
  const links = pageLinks(t)
  const { main, more } = navOfRole(role)
  return {
    main: main.map((page) => links[page]),
    more: [
      ...more.map((page) => links[page]),
      ...(signedIn ? [{ label: t('nav.password'), to: routes.password() }] : []),
    ],
  }
}

/** The role comes from core, and asking it needs a session */
const SignedInNav = ({ children }: { children: (links: NavLinks) => React.ReactNode }) => {
  const t = useT()
  const role = boxRoleQuery.useQuery().data?.role
  return <>{children(navLinks(t, role, true))}</>
}

/** Signed out, no pages at all: each of them leads back to the sign-in, and the form is all there is to do */
const RoleNav = ({ me, children }: { me: Me | null | undefined; children: (links: NavLinks) => React.ReactNode }) =>
  me ? <SignedInNav>{children}</SignedInNav> : null

// Right of the header: the sign-out, when signed in; signed out, the page itself is the sign-in
const accountLinks = (me: Me | null | undefined, t: T): NavItem[] =>
  me ? [{ label: t('nav.signOut'), to: routes.signOut() }] : []

/** The pages opened now and then; the trigger is marked when one of them is the current page */
const MoreMenu = ({ links }: { links: NavItem[] }) => {
  const t = useT()
  const { pathname } = useLocation()
  const current = links.some((link) => link.to === pathname)
  if (links.length === 0) {
    return null
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          'flex items-center gap-1 font-accent text-sm text-muted-foreground transition-colors outline-none hover:text-foreground',
          current && 'font-semibold text-foreground',
        )}
      >
        {t('nav.more')}
        <ChevronDown className="size-3.5" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-auto min-w-44">
        {links.map((link) => (
          <DropdownMenuItem key={link.label} asChild>
            <NavLink to={link.to} className={({ exact }) => cn('font-accent', exact && 'font-semibold')}>
              {link.label}
            </NavLink>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

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
          <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
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
              {me && (
                <nav className="hidden items-center gap-6 lg:flex">
                  <RoleNav me={me}>
                    {(links) => (
                      <>
                        <NavItems links={links.main} />
                        <MoreMenu links={links.more} />
                      </>
                    )}
                  </RoleNav>
                </nav>
              )}
            </div>

            <div className="hidden items-center gap-6 lg:flex">
              {me && (
                <nav className="flex items-center gap-6">
                  <NavItems links={accountLinks(me, t)} />
                </nav>
              )}
              <LanguageSwitcher />
              <ThemeSwitcher compact />
              <PaletteSwitcher />
            </div>

            <div className="flex items-center gap-1 lg:hidden">
              <LanguageSwitcher />
              <ThemeSwitcher compact />
              <PaletteSwitcher />
              {me && (
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
                      <RoleNav me={me}>
                        {(links) => (
                          <>
                            <NavItems
                              links={links.main}
                              className={mobileLinkClassName}
                              onNavigate={() => setMenuOpen(false)}
                            />
                            <div className="my-2 h-px bg-border" />
                            <NavItems
                              links={links.more}
                              className={mobileLinkClassName}
                              onNavigate={() => setMenuOpen(false)}
                            />
                          </>
                        )}
                      </RoleNav>
                      <div className="my-2 h-px bg-border" />
                      <NavItems
                        links={accountLinks(me, t)}
                        className={mobileLinkClassName}
                        onNavigate={() => setMenuOpen(false)}
                      />
                    </div>
                  </DrawerContent>
                </Drawer>
              )}
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 lg:py-12" data-layout-content>
          {children}
        </main>
      </div>
    )
  })
