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
import { cn } from '@/utils'
import { Menu, X } from 'lucide-react'
import { type ComponentProps, useState } from 'react'

type NavItem = { label: string; to: string }

// Left of the header — your top-level pages.
const navLinks: NavItem[] = [
  { label: 'Status', to: routes.home() },
  { label: 'Devices', to: routes.devices() },
  { label: 'Node', to: routes.node() },
]

// Right of the header — depends on who's signed in.
const accountLinks = (me: Me | null | undefined): NavItem[] =>
  !me ? [{ label: 'Sign In', to: routes.signIn() }] : [{ label: 'Sign Out', to: routes.signOut() }]

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

export const generalLayout = root.lets.layout().layout(({ children }) => {
  const me = getMeQuery.useQuery().data?.me
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
              <NavItems links={navLinks} />
            </nav>
          </div>

          <div className="hidden items-center gap-6 md:flex">
            <nav className="flex items-center gap-6">
              <NavItems links={accountLinks(me)} />
            </nav>
            <ThemeSwitcher compact />
          </div>

          <div className="flex items-center gap-1 md:hidden">
            <ThemeSwitcher compact />
            <Drawer open={menuOpen} onOpenChange={setMenuOpen} direction="right">
              <DrawerTrigger asChild>
                <Button variant="ghost" size="icon-default" aria-label="Open menu" icon={Menu} />
              </DrawerTrigger>
              <DrawerContent className="w-[80vw] max-w-xs text-foreground">
                <DrawerTitle className="sr-only">Menu</DrawerTitle>
                <DrawerDescription className="sr-only">Primary navigation</DrawerDescription>
                <div className="flex flex-col gap-1 p-4">
                  <DrawerClose asChild className="mb-2 self-end">
                    <Button variant="ghost" size="icon-default" aria-label="Close menu" icon={X} />
                  </DrawerClose>
                  <NavItems links={navLinks} className={mobileLinkClassName} onNavigate={() => setMenuOpen(false)} />
                  <div className="my-2 h-px bg-border" />
                  <NavItems
                    links={accountLinks(me)}
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
