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
    ? (['home', 'peers', 'node', 'access', 'notifications'] as const)
    : (['home', 'devices', 'rules', 'node', 'network', 'uplinks', 'access', 'notifications', 'journal'] as const)
