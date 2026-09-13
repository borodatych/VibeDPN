import { mixpanelTrackEvent } from '@/modules/mixpanel/shared'
import { useLocation } from '@point0/core/navigation'
import { useEffect } from 'react'

/**
 * Mixpanel's page-view tracker: sends a `Page Viewed` event on the initial load and on every client-side navigation.
 * Mixpanel's built-in `track_pageview` is off (see `client.ts`) because it can't see SPA route changes; this reads the
 * Point0 router location via `useLocation` instead, so the event fires on the page actually shown — not at navigation
 * start (which may still redirect or error). `useOnNavigate` is the wrong tool here: it skips the first load and fires
 * early.
 *
 * Each event carries `path` (concrete pathname) and `route` (the matched template, e.g. `/users/:id`, for grouping).
 * Query and hash are deliberately excluded — they'd spam pageviews and risk leaking params. Mount once near the app
 * root, inside `<Router>`. No-op when Mixpanel is disabled (handled by `mixpanelTrackEvent`).
 *
 * Each analytics tool ships its own self-contained `*TrackPage` (e.g. a future `GATrackPage` for Google) — they just
 * subscribe to the router independently; no shared wiring, and no children means no re-render cost.
 *
 * @tags mixpanel
 * @related mixpanelTrackEvent, MixpanelTrackAuth
 */
export const MixpanelTrackPage = (): null => {
  const location = useLocation()

  useEffect(() => {
    mixpanelTrackEvent('Page Viewed', {
      path: location.pathname,
      ...(location.route ? { route: location.route } : {}),
    })
  }, [location.pathname, location.route])

  return null
}
