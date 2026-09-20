/** A WireGuard exit of `GET /uplinks/wg` (core/vibedpn/api/models.py: WgUplinkView); its file never comes back. */
export type WgExit = { name: string; enabled: boolean; has_file: boolean }

/** The last change the host applied for the panel (core/vibedpn/api/models.py: ApplyView). */
export type ApplyView = { pending: boolean; ok: boolean | null; message: string; finished_at: number | null }

export type WgExits = { uplinks: WgExit[]; apply: ApplyView }

/** Uplink tor of `GET /uplinks/tor` (core/vibedpn/api/models.py: TorUplinkView); a bridge is its transport and address. */
export type TorExit = { enabled: boolean; bridges: string[]; apply: ApplyView }

/** The routing key of the exit through Tor, as core names it in `routing.default_upstream` and in `GET /status`. */
export const TOR_KEY = 'tor'

/** Uplink xray of `GET /uplinks/xray` (core/vibedpn/api/models.py: XrayUplinkView); the share link never comes back. */
export type XrayExit = {
  enabled: boolean
  linked: boolean
  endpoint: string
  transport: string
  remark: string
  problem: string
  apply: ApplyView
}

/** The routing key of the masking exit, as core names it in `routing.default_upstream`. */
export const XRAY_KEY = 'xray'

/** core/vibedpn/api/models.py XrayUplinkUpdate: the link is a credential, and a long one. */
export const MAX_XRAY_LINK_BYTES = 4 * 1024

/** What every usable share link starts with; core parses the rest and says what is wrong. */
export const XRAY_LINK_PREFIX = 'vless://'

/** Whether this text can be a share link at all — the full check belongs to core. */
export const xrayLinkProblem = (text: string): 'empty' | 'scheme' | null => {
  const value = text.trim()
  if (!value) {
    return 'empty'
  }
  return value.startsWith(XRAY_LINK_PREFIX) ? null : 'scheme'
}

/** The routing key of an exit, as core names it in `routing.default_upstream` and in `GET /status`. */
export const exitKey = (name: string): string => `wg-${name}`

/** core/vibedpn/config.py WG_UPLINK_NAME: the name becomes a file, a container and a routing key. */
export const WG_EXIT_NAME = /^[a-z0-9][a-z0-9-]{0,23}$/
const WG_EXIT_NAME_MAX = 24
/** core/vibedpn/bootstrap.py MAX_PEER_FILE_BYTES */
export const MAX_WG_FILE_BYTES = 64 * 1024
const DEFAULT_EXIT_NAME = 'proton'
/** core/vibedpn/bootstrap.py PEER_FILE_MARKERS: what every usable WireGuard client file carries. */
const WG_FILE_MARKERS = ['[Interface]', 'PrivateKey', '[Peer]', 'PublicKey'] as const

/** Where Proton VPN hands out its WireGuard files: the account, and its own guide to the page. */
export const PROTON_ACCOUNT_URL = 'https://account.protonvpn.com'
export const PROTON_GUIDE_URL = 'https://protonvpn.com/support/wireguard-configurations'

/**
 * A usable exit name from the name of a downloaded file: `Proton NL#12.conf` → `proton-nl-12`. A name that cannot be
 * made usable gives the default, which the owner changes before adding.
 *
 * @tags uplinks
 */
export const suggestExitName = (fileName: string): string => {
  const name = fileName
    .replace(/\.conf$/i, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+/, '')
    .slice(0, WG_EXIT_NAME_MAX)
    .replace(/-+$/, '')
  return WG_EXIT_NAME.test(name) ? name : DEFAULT_EXIT_NAME
}

/**
 * What a text lacks to be a WireGuard client file; empty when it looks like one. Only a hint before sending: core
 * checks the file itself and has the last word.
 *
 * @tags uplinks
 */
export const missingWgParts = (text: string): string[] => WG_FILE_MARKERS.filter((marker) => !text.includes(marker))
