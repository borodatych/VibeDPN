import type { T } from '@/modules/i18n/base'

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

export const deviceLabel = (device: Device, t: T): string =>
  device.name ?? device.hostname ?? device.mac ?? device.ip ?? t('devices.unknown')

/**
 * The policy list of a device row; a policy through an uplink that is not enabled cannot be chosen (core would refuse
 * it).
 *
 * @tags devices
 */
export const policyOptions = (enabled: { vps: boolean; dpn: boolean }, t: T) => [
  { value: 'mode', label: t('devices.policy.mode') },
  { value: 'vps', label: t('devices.policy.vps'), disabled: !enabled.vps },
  { value: 'dpn', label: t('devices.policy.dpn'), disabled: !enabled.dpn },
  { value: 'bypass', label: t('devices.policy.bypass') },
  { value: 'block', label: t('devices.policy.block') },
]

/** Case-insensitive search over what the owner can read in the row. */
export const matchesSearch = (device: Device, query: string): boolean => {
  const needle = query.trim().toLowerCase()
  if (!needle) {
    return true
  }
  return [device.name, device.hostname, device.mac, device.ip].some((field) => field?.toLowerCase().includes(needle))
}
