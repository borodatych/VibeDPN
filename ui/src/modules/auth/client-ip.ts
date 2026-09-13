import type { Request0 } from '@point0/core/request0'
import '@point0/core/server-only'

/**
 * The only header better-auth reads the client address from (`advanced.ipAddress.ipAddressHeaders`). Nothing stands in
 * front of the panel, so every forwarding header a LAN device sends is a claim, not a fact: trusting `x-forwarded-for`
 * let a device rotate it and sign in without ever hitting the rate limit.
 *
 * @tags rule, auth
 * @related withSocketClientIp
 */
export const CLIENT_IP_HEADER = 'x-vibedpn-client-ip'

const FORWARDING_HEADERS = [
  'x-forwarded-for',
  'x-real-ip',
  'forwarded',
  'x-client-ip',
  'true-client-ip',
  'cf-connecting-ip',
  CLIENT_IP_HEADER,
]

/** The request for better-auth: forwarding headers dropped, the socket peer (`request.from.ip`) in their place. */
export const withSocketClientIp = (request: Request0) => {
  const headers = new Headers(request.original.headers)
  for (const name of FORWARDING_HEADERS) {
    headers.delete(name)
  }
  const ip = request.from.ip
  if (ip) {
    headers.set(CLIENT_IP_HEADER, ip)
  }
  return new Request(request.original, { headers })
}
