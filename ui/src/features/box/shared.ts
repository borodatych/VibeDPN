/** core/vibedpn/config.py Role.VPS: a box with peers and a node, and no LAN of its own. */
export const VPS_ROLE = 'vps'

/**
 * The top-level pages a role has, by route name: a VPS routes no LAN, so it has no devices, rules, network, exits or
 * journal, and it has the peers of its tunnel instead.
 *
 * @tags box
 */
export const pagesOfRole = (role: string | null | undefined) =>
  role === VPS_ROLE
    ? (['home', 'peers', 'node', 'access', 'notifications', 'backup'] as const)
    : ([
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
      ] as const)

// The pages a box opens now and then: in the menu «Ещё» of the header, so the header fits a laptop screen
// Per role: the node is a main page of a VPS, which has few pages, and a side one of a box with a LAN
const MORE_PAGES: readonly string[] = ['node', 'notifications', 'journal', 'backup']
const MORE_PAGES_VPS: readonly string[] = ['notifications', 'backup']

/**
 * The pages of a role split for the header: the ones in sight, and the ones in the menu «Ещё»
 * Every page of the role is in exactly one of them, in the order of `pagesOfRole`
 *
 * @tags box
 */
export const navOfRole = (role: string | null | undefined) => {
  const pages = pagesOfRole(role)
  const more = role === VPS_ROLE ? MORE_PAGES_VPS : MORE_PAGES
  return {
    main: pages.filter((page) => !more.includes(page)),
    more: pages.filter((page) => more.includes(page)),
  }
}
