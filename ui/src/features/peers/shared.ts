/** One peer of `GET /peers` (core/vibedpn/api/models.py: PeerView); never with its private key. */
export type Peer = {
  name: string
  address: string
  public_key: string
  created: string
  endpoint: string | null
  /** unix seconds; 0: no handshake yet; null: core cannot read the interface */
  latest_handshake: number | null
  rx_bytes: number | null
  tx_bytes: number | null
  /** null: core cannot read the interface; false: registered, not on wg0 yet; true: on wg0 */
  applied: boolean | null
  tunnel_only: boolean
}

/** The WireGuard file of a peer, from `POST /peers` and `GET /peers/{name}/config`: it holds the private key. */
export type PeerFile = { name: string; address: string; config: string; qr_svg: string }

/** Totals of one peer over a period, kept across restarts of the tunnel (`GET /peers/traffic`). */
export type PeerTraffic = { name: string; public_key: string; rx_bytes: number; tx_bytes: number }

/**
 * A peer name as core takes it (core/vibedpn/engine/wg.py PEER_NAME): it ends up in file names and the CLI.
 *
 * @tags peers
 */
export const PEER_NAME = /^[a-z0-9][a-z0-9-]{0,31}$/

// The file a peer is handed as, so the WireGuard app and `vibedpn uplink add` see a .conf
const PEER_FILE_EXTENSION = '.conf'

/** The name of the file a peer is downloaded as. */
export const peerFileName = (name: string): string => `${name}${PEER_FILE_EXTENSION}`

// core/vibedpn/engine/wg.py: a peer with PersistentKeepalive handshakes about every two minutes
const HANDSHAKE_FRESH_SECONDS = 180

export type PeerLinkState = 'unknown' | 'pending' | 'never' | 'online' | 'offline'

/**
 * How a peer is doing on the tunnel now: pending until wg-server applies it, online while its handshake is fresh.
 *
 * @tags peers
 */
export const peerLinkState = (peer: Peer, nowSeconds: number): PeerLinkState => {
  // a peer not on wg0 yet has no live fields either: registered, waiting for wg-server
  if (peer.applied === false) {
    return 'pending'
  }
  if (peer.applied === null || peer.latest_handshake === null) {
    return 'unknown'
  }
  if (peer.latest_handshake === 0) {
    return 'never'
  }
  return nowSeconds - peer.latest_handshake <= HANDSHAKE_FRESH_SECONDS ? 'online' : 'offline'
}

// The period the totals of the peers page cover
export const TRAFFIC_DAYS = 30
const DAY_MS = 24 * 60 * 60 * 1000

/** The first day of the period as core takes it: `YYYY-MM-DD`. */
export const trafficSince = (now: Date, days: number = TRAFFIC_DAYS): string =>
  new Date(now.getTime() - (days - 1) * DAY_MS).toISOString().slice(0, 10)

/** The pseudo-entry of the list of peers that opens the form adding one */
export const ADD_PEER = 'add'

/**
 * The entry «Peers» shows: the peer in the URL when the VPS has it, else the first peer, else the form adding one
 * A peer removed while it was open falls back the same way
 *
 * @tags peers
 */
export const pickPeer = (names: string[], wanted: string | undefined): string => {
  if (wanted !== undefined && (wanted === ADD_PEER || names.includes(wanted))) {
    return wanted
  }
  return names.at(0) ?? ADD_PEER
}

