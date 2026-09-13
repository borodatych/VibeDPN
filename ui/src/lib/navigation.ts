import { createNavigation } from '@point0/react-dom/router'
import { navigate as browserNavigate, useBrowserLocation as hook } from 'wouter/use-browser-location'
import { routes } from '@/generated/point0/routes'
import { AppError } from '@/lib/error'

export const { navigate, Link, NavLink, Redirect, redirect, Router, RouterRoutes, useNavLink, InferNavigation } =
  createNavigation({
    routes,
    navigate: browserNavigate,
    hook,
    ErrorClass: AppError,
  })

// Embeddable link props with this app's routes baked in — merge into any component's
// props (`& AppLinkProps`) and split out at runtime with `splitLinkProps`.
export type AppLinkProps = typeof InferNavigation.LinkProps
export type AppNavLinkProps = typeof InferNavigation.NavLinkProps
