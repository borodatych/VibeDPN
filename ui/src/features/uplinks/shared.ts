/** A WireGuard exit of `GET /uplinks/wg` (core/vibedpn/api/models.py: WgUplinkView); its file never comes back. */
export type WgExit = { name: string; enabled: boolean; has_file: boolean }

/** The last change the host applied for the panel (core/vibedpn/api/models.py: ApplyView). */
export type ApplyView = { pending: boolean; ok: boolean | null; message: string; finished_at: number | null }

export type WgExits = { uplinks: WgExit[]; apply: ApplyView }

/**
 * Uplink tor of `GET /uplinks/tor` (core/vibedpn/api/models.py: TorUplinkView)
 *
 * A bridge is its transport and address: the rest of a private bridge line never comes back
 */
export type TorExit = { enabled: boolean; bridges: string[]; custom: boolean; apply: ApplyView }

/** core/vibedpn/config.py TOR_TRANSPORTS: the transports the gateway image has a client for. */
export const TOR_TRANSPORTS = ['snowflake', 'obfs4', 'meek_lite'] as const
/** core/vibedpn/api/models.py TorBridgesUpdate: lines and the length of each */
export const MAX_TOR_BRIDGES = 64
export const MAX_TOR_BRIDGE_LINE = 4 * 1024
// A transport Tor knows and the gateway does not: named apart, it is the one owners most often paste
const WEBTUNNEL = 'webtunnel'
// core/vibedpn/config.py TORRC_BRIDGE_KEYWORD: torrc options are case-insensitive
const TORRC_BRIDGE_KEYWORD = 'bridge'

/** The bridge lines of a pasted text, as core keeps them: blank lines dropped, a torrc `Bridge` keyword too. */
export const bridgeLines = (text: string): string[] =>
  text
    .split('\n')
    .map((raw) => raw.trim())
    .filter(Boolean)
    .map((line) => {
      const [keyword = '', ...rest] = line.split(/\s+/)
      return keyword.toLowerCase() === TORRC_BRIDGE_KEYWORD ? rest.join(' ') : line
    })

/**
 * What keeps a pasted text from being bridges the gateway can run, or null; core checks again and has the last word
 *
 * `line` is the number of the first bad line among the non-blank ones, counted from 1
 *
 * @tags uplinks
 */
export const bridgeLinesProblem = (
  text: string,
): { kind: 'empty' | 'tooMany' } | { kind: 'webtunnel' | 'line'; line: number } | null => {
  const lines = bridgeLines(text)
  if (!lines.length) {
    return { kind: 'empty' }
  }
  if (lines.length > MAX_TOR_BRIDGES) {
    return { kind: 'tooMany' }
  }
  const bad = lines.findIndex((line) => {
    const words = line.split(/\s+/)
    return (
      words.length < 2 ||
      line.length > MAX_TOR_BRIDGE_LINE ||
      !(TOR_TRANSPORTS as readonly string[]).includes(words[0]!)
    )
  })
  if (bad === -1) {
    return null
  }
  return { kind: lines[bad]!.split(/\s+/)[0] === WEBTUNNEL ? 'webtunnel' : 'line', line: bad + 1 }
}

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

/** An entry of the list of exits on «Exits»: the kind of exit, its key (the URL and the service) and whether it is on */
export type ExitEntry = { key: string; kind: 'tor' | 'xray' | 'wg'; on: boolean }

/** The pseudo-entry of the list that opens the form adding a WireGuard exit */
export const ADD_EXIT = 'add'

/**
 * The exits of the list in a fixed order: Tor, the masking exit, then the WireGuard exits of the box
 *
 * @tags uplinks
 */
export const exitEntries = (
  tor: { enabled: boolean } | undefined,
  xray: { enabled: boolean } | undefined,
  wg: WgExit[],
): ExitEntry[] => [
  ...(tor ? [{ key: TOR_KEY, kind: 'tor' as const, on: tor.enabled }] : []),
  ...(xray ? [{ key: XRAY_KEY, kind: 'xray' as const, on: xray.enabled }] : []),
  ...wg.map((exit) => ({ key: exitKey(exit.name), kind: 'wg' as const, on: exit.enabled && exit.has_file })),
]

/**
 * The entry the page shows: the one in the URL when the box has it, else the first exit that is on, else the first A
 * WireGuard exit removed while it was open falls back the same way, never to an empty page
 *
 * @tags uplinks
 */
export const pickExit = (entries: ExitEntry[], wanted: string | undefined): string => {
  if (wanted !== undefined && (wanted === ADD_EXIT || entries.some((entry) => entry.key === wanted))) {
    return wanted
  }
  const chosen = entries.find((entry) => entry.on) ?? entries.at(0)
  return chosen ? chosen.key : ADD_EXIT
}
