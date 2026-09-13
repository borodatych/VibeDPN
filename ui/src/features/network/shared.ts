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
export const lanOptions = (view: NetworkView): { value: string; label: string }[] => {
  const wan = view.interfaces.find((item) => item.default_route)
  return [
    { value: SIDECAR, label: `One port: in the home LAN on ${wan?.name ?? 'the default-route interface'}` },
    ...view.interfaces
      .filter((item) => !item.default_route)
      .map((item) => ({
        value: item.name,
        label: `Gateway: LAN ${item.name} ${item.address}/${item.prefixlen}, WAN ${wan?.name ?? '?'}`,
      })),
  ]
}

export const currentChoice = (view: NetworkView): string => (view.mode === 'gateway' ? view.lan_interface : SIDECAR)
