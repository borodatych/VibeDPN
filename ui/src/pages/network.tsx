import { Section } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { networkQuery, networkUpdateMutation } from '@/features/network/api'
import { currentChoice, lanOptions, SIDECAR } from '@/features/network/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'

export const networkPage = generalLayout.lets
  .page('/network')
  .head('Network')
  .use(redirectUnauthorizedPlugin)
  .with(networkQuery)
  .page(({ data: { network } }) => {
    const mutation = networkUpdateMutation.useMutation()

    const choose = async (value: string) => {
      await mutation.mutateAsync({ lan_interface: value === SIDECAR ? null : value })
      await networkQuery.refetchQuery()
    }

    return (
      <Section h1="Network" description="Where the box stands: in the home LAN on one port, or between the ISP and the LAN">
        <XSelect
          options={lanOptions(network)}
          value={currentChoice(network)}
          disabled={mutation.isPending}
          onValueChange={(value) => void choose(String(value))}
        />
        <p className="mt-2 text-sm text-muted-foreground">
          {network.mode === 'gateway'
            ? `The box hands out addresses on ${network.lan_interface}; its devices use ${network.lan_address} as gateway and DNS.`
            : `The box sits in the home LAN at ${network.lan_address}; devices use it as their gateway.`}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Only interfaces with an IPv4 address are listed: the system gives the LAN interface its address.
        </p>
        {mutation.error && <p className="mt-2 text-sm text-destructive">{mutation.error.message}</p>}
        {network.restart_required && (
          <p className="mt-4 rounded-md border p-3 text-sm">
            Saved, not applied yet. Run <code>sudo vibedpn restart</code> on the box; the panel then opens at{' '}
            <code>{network.lan_address}</code>.
          </p>
        )}
      </Section>
    )
  })
