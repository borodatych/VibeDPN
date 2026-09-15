import { useHead } from '@unhead/react'
import { Section } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { networkQuery, networkUpdateMutation } from '@/features/network/api'
import { currentChoice, lanOptions, SIDECAR } from '@/features/network/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'

export const networkPage = generalLayout.lets
  .page('/network')
  .use(redirectUnauthorizedPlugin)
  .with(networkQuery)
  .page(({ data: { network } }) => {
    const mutation = networkUpdateMutation.useMutation()
    const t = useT()
    useHead({ title: t('nav.network') })

    const choose = async (value: string) => {
      await mutation.mutateAsync({ lan_interface: value === SIDECAR ? null : value })
      await networkQuery.refetchQuery()
    }

    return (
      <Section h1={t('network.title')} description={t('network.description')}>
        <XSelect
          options={lanOptions(network, t)}
          value={currentChoice(network)}
          disabled={mutation.isPending}
          onValueChange={(value) => void choose(String(value))}
        />
        <p className="mt-2 text-sm text-muted-foreground">
          {network.mode === 'gateway'
            ? t('network.gatewayHint', { interface: network.lan_interface, address: network.lan_address })
            : t('network.sidecarHint', { address: network.lan_address })}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{t('network.onlyWithAddress')}</p>
        {mutation.error && <p className="mt-2 text-sm text-destructive">{mutation.error.message}</p>}
        {network.restart_required && (
          <p className="mt-4 rounded-md border p-3 text-sm">
            {t('network.saved', { command: 'sudo vibedpn restart', address: network.lan_address })}
          </p>
        )}
      </Section>
    )
  })
