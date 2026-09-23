import type { ApplyView } from '@/features/uplinks/shared'

/** A person of `GET /access` (core/vibedpn/api/models.py: AccessPerson); their id never comes to the panel. */
export type AccessPerson = { name: string; created: string; rx_bytes: number; tx_bytes: number }

/** The access server of `GET /access` (core/vibedpn/api/models.py: AccessView). */
export type AccessServer = {
  enabled: boolean
  address: string
  port: number
  target: string
  people: AccessPerson[]
  apply: ApplyView
}

/** The link of one person with the same link as an SVG QR code (core/vibedpn/api/models.py: AccessLink). */
export type AccessLink = { name: string; link: string; qr_svg: string }

/** ddns of `GET /ddns` (core/vibedpn/api/models.py: DdnsView); the update URL never comes back, only its service. */
export type Ddns = {
  enabled: boolean
  url_set: boolean
  host: string
  public_ip: string | null
  told_ip: string | null
  last_ok: boolean | null
  last_at: number | null
  message: string
  apply: ApplyView
}

/** core/vibedpn/engine/wg.py PEER_NAME, which the people share with the peers: it names a user of the server. */
export const PERSON_NAME = /^[a-z0-9][a-z0-9-]{0,31}$/
export const PERSON_NAME_MAX = 32

/** core/vibedpn/engine/ddns.py URL_PATTERN: https only, because the token travels in the URL. */
const DDNS_URL = /^https:\/\/[^\s/]+\/\S*$/
export const MAX_DDNS_URL_BYTES = 2 * 1024

/** core/vibedpn/config.py: a hostname or an IPv4 address; core has the last word. */
const ADDRESS = /^[A-Za-z0-9.-]{1,253}$/

/**
 * Why this text cannot be the name of a person yet; `null` when it can.
 *
 * @tags access
 */
export const personNameProblem = (name: string): 'empty' | 'format' | null => {
  if (!name) {
    return 'empty'
  }
  return PERSON_NAME.test(name) ? null : 'format'
}

/**
 * Why this text cannot be an update URL; `null` when it can. Only a hint before sending: core checks it again.
 *
 * @tags access
 */
export const ddnsUrlProblem = (text: string): 'empty' | 'https' | null => {
  const value = text.trim()
  if (!value) {
    return 'empty'
  }
  return DDNS_URL.test(value) ? null : 'https'
}

/**
 * Whether this text can be the address the links name.
 *
 * @tags access
 */
export const addressLooksValid = (text: string): boolean => ADDRESS.test(text.trim())

/**
 * The QR code core rendered, as an image source: an `<img>` runs nothing an SVG could carry.
 *
 * @tags access
 */
export const qrImageSource = (svg: string): string => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
