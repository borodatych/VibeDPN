import type { T } from '@/modules/i18n/base'

/** One interface of core's `GET /network` (core/vibedpn/api/models.py: HostInterface). */
export type HostInterface = {
  name: string
  address: string
  prefixlen: number
  default_route: boolean
}

/** Core's `GET /network` and `PUT /network` (core/vibedpn/api/models.py: NetworkView). */
export type NetworkView = {
  mode: 'sidecar' | 'gateway'
  lan_interface: string
  lan_address: string
  wan_interface: string | null
  restart_required: boolean
  interfaces: HostInterface[]
}

/** The select value of one port: the box stays in the LAN next to the ISP router. */
export const SIDECAR = 'sidecar'

/**
 * The LAN choices: one port on the default-route interface, or any other interface with an address as the LAN of
 * gateway mode, the default-route one becoming the WAN.
 *
 * @tags network
 */
export const lanOptions = (view: NetworkView, t: T): { value: string; label: string }[] => {
  const wan = view.interfaces.find((item) => item.default_route)
  return [
    {
      value: SIDECAR,
      label: t('network.option.sidecar', { interface: wan?.name ?? t('network.option.defaultRoute') }),
    },
    ...view.interfaces
      .filter((item) => !item.default_route)
      .map((item) => ({
        value: item.name,
        label: t('network.option.gateway', {
          interface: item.name,
          address: item.address,
          prefix: item.prefixlen,
          wan: wan?.name ?? '?',
        }),
      })),
  ]
}

export const currentChoice = (view: NetworkView): string => (view.mode === 'gateway' ? view.lan_interface : SIDECAR)

/** Core's `PUT /wifi/passphrase` (core/vibedpn/api/models.py: WifiPassphraseView). */
export type WifiPassphraseView = {
  result: 'applied' | 'unchanged' | 'pending'
  error: string
}

// An ASCII passphrase of WPA-PSK, as core/vibedpn/engine/hostapd.py takes it
export const PASSPHRASE_MIN = 8
export const PASSPHRASE_MAX = 63
const PRINTABLE_ASCII = /^[\x20-\x7e]*$/

export type PassphraseProblem = 'length' | 'characters' | 'spaces' | 'mismatch'

/**
 * Why a new Wi-Fi passphrase cannot be sent yet; `null` when it can. Only a hint before sending: core checks the same
 * rules again.
 *
 * @tags network
 */
export const passphraseProblem = (value: string, repeat: string): PassphraseProblem | null => {
  if (value.length < PASSPHRASE_MIN || value.length > PASSPHRASE_MAX) {
    return 'length'
  }
  if (!PRINTABLE_ASCII.test(value)) {
    return 'characters'
  }
  if (value !== value.trim()) {
    return 'spaces'
  }
  return value === repeat ? null : 'mismatch'
}
