/** One entry of core's `GET /devices` (core/vibedpn/api/models.py: DeviceView). */
export type Device = {
  mac: string | null
  ip: string | null
  name: string | null
  hostname: string | null
  policy: DevicePolicy | null
  seen: boolean
  first_seen: string | null
  last_seen: string | null
}

export type DevicePolicy = 'vps' | 'dpn' | 'bypass' | 'block'

/** The choice in the table: an own policy, or none — the device follows routing.mode. */
export type PolicyChoice = DevicePolicy | 'mode'

export const DEVICE_POLICIES = ['vps', 'dpn', 'bypass', 'block'] as const

/** What core addresses a device by: the MAC when known, the address otherwise. */
export const deviceIdent = (device: Device): string => device.mac ?? device.ip ?? ''

export const deviceLabel = (device: Device): string =>
  device.name ?? device.hostname ?? device.mac ?? device.ip ?? 'Unknown device'

/**
 * The policy list of a device row; a policy through an uplink that is not enabled cannot be chosen (core would refuse it).
 *
 * @tags devices
 */
export const policyOptions = (enabled: { vps: boolean; dpn: boolean }) => [
  { value: 'mode', label: 'Follows the mode' },
  { value: 'vps', label: 'Through the VPS', disabled: !enabled.vps },
  { value: 'dpn', label: 'Through Mysterium', disabled: !enabled.dpn },
  { value: 'bypass', label: 'Direct (bypass)' },
  { value: 'block', label: 'No internet (block)' },
]

/** Case-insensitive search over what the owner can read in the row. */
export const matchesSearch = (device: Device, query: string): boolean => {
  const needle = query.trim().toLowerCase()
  if (!needle) {
    return true
  }
  return [device.name, device.hostname, device.mac, device.ip].some((field) => field?.toLowerCase().includes(needle))
}
