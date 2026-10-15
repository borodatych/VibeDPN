/** core/vibedpn/config.py Role.VPS: a box with peers and a node, and no LAN of its own. */
export const VPS_ROLE = 'vps'

const VPS_PAGES = ['home', 'peers', 'node', 'access', 'notifications', 'backup'] as const
const LAN_PAGES = [
  'home',
  'devices',
  'rules',
  'node',
  'network',
  'uplinks',
  'access',
  'notifications',
  'journal',
  'backup',
] as const
// The torrent client sits after the exits and the access: a page of use, not of setting the box up
const LAN_PAGES_WITH_TORRENTS = [
  'home',
  'devices',
  'rules',
  'node',
  'network',
  'uplinks',
  'access',
  'torrents',
  'notifications',
  'journal',
  'backup',
] as const

/**
 * The top-level pages a role has, by route name: a VPS routes no LAN, so it has no devices, rules, network, exits or
 * journal, and it has the peers of its tunnel instead. The torrents page is for the roles with a LAN, and only while
 * the service is on.
 *
 * @tags box
 */
export const pagesOfRole = (role: string | null | undefined, torrents = false) =>
  role === VPS_ROLE ? VPS_PAGES : torrents ? LAN_PAGES_WITH_TORRENTS : LAN_PAGES

// The pages a box opens now and then: in the menu «Ещё» of the header, so the header fits a laptop screen
// Per role: the node is a main page of a VPS, which has few pages, and a side one of a box with a LAN
const MORE_PAGES: readonly string[] = ['torrents', 'node', 'notifications', 'journal', 'backup']
const MORE_PAGES_VPS: readonly string[] = ['notifications', 'backup']

/**
 * The pages of a role split for the header: the ones in sight, and the ones in the menu «Ещё» Every page of the role is
 * in exactly one of them, in the order of `pagesOfRole`
 *
 * @tags box
 */
export const navOfRole = (role: string | null | undefined, torrents = false) => {
  const pages = pagesOfRole(role, torrents)
  const more = role === VPS_ROLE ? MORE_PAGES_VPS : MORE_PAGES
  return {
    main: pages.filter((page) => !more.includes(page)),
    more: pages.filter((page) => more.includes(page)),
  }
}
