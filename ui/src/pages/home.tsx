import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Section, Sections } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import {
  boxStatusQuery,
  dpnCountriesQuery,
  dpnCountryMutation,
  routingUpdateMutation,
  vpsLanAccessMutation,
} from '@/features/status/api'
import { formatMyst } from '@/features/node/shared'
import { summarizeStatus, type BoxStatus, type DpnStatus, type UplinkStatus } from '@/features/status/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'

const TONE_BADGE = { ok: 'success', warning: 'warning', danger: 'destructive' } as const

const gatewayText = (alive: boolean | null, t: T) => {
  if (alive === null) {
    return t('uplink.gatewayState.notProbed')
  }
  return alive ? t('uplink.gatewayState.answers') : t('uplink.gatewayState.silent')
}

const killSwitchText = (uplink: UplinkStatus, failopen: boolean, t: T) => {
  if (failopen) {
    return t('uplink.killSwitchState.failopen')
  }
  if (uplink.kill_switch_route === null) {
    return t('uplink.killSwitchState.unreadable')
  }
  return uplink.kill_switch_route ? t('uplink.killSwitchState.armed') : t('uplink.killSwitchState.missing')
}

const VpsLanAccess = ({ allowed }: { allowed: boolean }) => {
  const mutation = vpsLanAccessMutation.useMutation()
  const t = useT()
  const change = async (next: boolean) => {
    await mutation.mutateAsync({ allowed: next })
    await boxStatusQuery.refetchQuery()
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span>{allowed ? t('lanAccess.open') : t('lanAccess.closed')}</span>
      {allowed ? (
        <Button variant="outline-secondary" size="sm" loading={mutation.isPending} onClick={() => void change(false)}>
          {t('lanAccess.closeAction')}
        </Button>
      ) : (
        <Button
          variant="outline-secondary"
          size="sm"
          loading={mutation.isPending}
          confirm={t('lanAccess.confirm')}
          onClick={() => void change(true)}
        >
          {t('lanAccess.openAction')}
        </Button>
      )}
      {mutation.isError && <span className="text-xs text-destructive">{mutation.error.message}</span>}
    </div>
  )
}

const UplinkCard = ({ uplink, failopen }: { uplink: UplinkStatus; failopen: boolean }) => {
  const t = useT()
  const language = useLanguage()
  return (
    <Section
      h2={uplink.name.toUpperCase()}
      size="lg"
      description={uplink.in_use ? t('uplink.inUse') : t('uplink.notInUse')}
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
        <dt className="text-muted-foreground">{t('uplink.gateway')}</dt>
        <dd>{uplink.in_use ? gatewayText(uplink.gateway_alive, t) : t('common.none')}</dd>
        <dt className="text-muted-foreground">{t('uplink.killSwitch')}</dt>
        <dd>{uplink.in_use ? killSwitchText(uplink, failopen, t) : t('common.none')}</dd>
        {uplink.lan_access !== null && (
          <>
            <dt className="text-muted-foreground">{t('uplink.lanAccess')}</dt>
            <dd>
              <VpsLanAccess allowed={uplink.lan_access} />
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">{t('uplink.checked')}</dt>
        <dd>{uplink.checked_at ? formatDate(new Date(uplink.checked_at), 'date-time', language) : t('common.none')}</dd>
        {uplink.error && (
          <>
            <dt className="text-muted-foreground">{t('uplink.error')}</dt>
            <dd className="text-destructive">{uplink.error}</dd>
          </>
        )}
      </dl>
    </Section>
  )
}

const RoutingControls = ({ status }: { status: BoxStatus }) => {
  const mutation = routingUpdateMutation.useMutation()
  const t = useT()
  const change = async (input: { mode?: 'off' | 'full'; default_upstream?: 'vps' | 'dpn' }) => {
    await mutation.mutateAsync(input)
    await boxStatusQuery.refetchQuery()
  }
  // The consumers of rule countries (dpn-<country>) serve their rules only: no mode goes through them.
  const enabled = status.uplinks.filter(
    (uplink): uplink is UplinkStatus & { name: 'vps' | 'dpn' } =>
      uplink.enabled && (uplink.name === 'vps' || uplink.name === 'dpn'),
  )
  return (
    <Section
      h2={t('routing.title')}
      size="lg"
      description={t('routing.failopen', { state: status.failopen ? t('routing.state.on') : t('routing.state.off') })}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-accent text-sm text-muted-foreground">{t('routing.mode')}</span>
        <Button
          variant={status.mode === 'off' ? 'default' : 'outline-secondary'}
          disabled={status.mode === 'off'}
          loading={mutation.isPending}
          onClick={() => void change({ mode: 'off' })}
        >
          {t('routing.modeOff')}
        </Button>
        <Button
          variant={status.mode === 'full' ? 'default' : 'outline-secondary'}
          disabled={status.mode === 'full'}
          loading={mutation.isPending}
          confirm={t('routing.confirmFull', { uplink: status.default_upstream })}
          onClick={() => void change({ mode: 'full' })}
        >
          {t('routing.modeFull')}
        </Button>
      </div>
      {enabled.length > 1 && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="font-accent text-sm text-muted-foreground">{t('routing.uplink')}</span>
          {enabled.map((uplink) => (
            <Button
              key={uplink.name}
              variant={status.default_upstream === uplink.name ? 'default' : 'outline-secondary'}
              disabled={status.default_upstream === uplink.name}
              loading={mutation.isPending}
              onClick={() => void change({ default_upstream: uplink.name })}
            >
              {uplink.name.toUpperCase()}
            </Button>
          ))}
        </div>
      )}
      {mutation.isError && <p className="mt-3 text-sm text-destructive">{mutation.error.message}</p>}
      {mutation.data?.routing.adguard === 'pending' && (
        <p className="mt-3 text-sm text-warning">{t('routing.adguardPending')}</p>
      )}
    </Section>
  )
}

const ANY_COUNTRY = 'any'

const ConsumerFacts = ({ dpn }: { dpn: DpnStatus }) => {
  const t = useT()
  return (
    <>
      <dt className="text-muted-foreground">{t('dpn.registration')}</dt>
      <dd>{dpn.registration}</dd>
      <dt className="text-muted-foreground">{t('dpn.connection')}</dt>
      <dd>{dpn.connection}</dd>
      <dt className="text-muted-foreground">{t('dpn.balance')}</dt>
      <dd>{t('common.myst', { amount: formatMyst(dpn.balance_wei) })}</dd>
      <dt className="text-muted-foreground">{t('dpn.topUp')}</dt>
      <dd className="font-mono text-xs break-all">{dpn.channel_address || t('common.none')}</dd>
    </>
  )
}

/** The consumer of one exit country of the domain rules: its identity is topped up on its own. */
const CountryConsumerCard = ({ dpn }: { dpn: DpnStatus }) => {
  const t = useT()
  return (
    <Section
      h2={t('dpn.countryTitle', { country: dpn.country ?? '' })}
      size="lg"
      description={dpn.identity ? t('dpn.identity', { identity: dpn.identity }) : t('dpn.noIdentity')}
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
        <ConsumerFacts dpn={dpn} />
      </dl>
      {dpn.error && <p className="mt-3 text-sm text-warning">{dpn.error}</p>}
    </Section>
  )
}

const DpnCard = ({ dpn }: { dpn: DpnStatus }) => {
  const countries = dpnCountriesQuery.useQuery()
  const mutation = dpnCountryMutation.useMutation()
  const t = useT()
  const offers = countries.data?.countries ?? []
  const options = [
    { value: ANY_COUNTRY, label: t('dpn.anyCountry') },
    ...offers.map((offer) => ({
      value: offer.country,
      label: t('dpn.offer', { country: offer.country, nodes: offer.nodes, price: formatMyst(offer.min_per_gib_wei) }),
    })),
  ]
  const choose = async (value: string) => {
    await mutation.mutateAsync({ country: value === ANY_COUNTRY ? null : value })
    await boxStatusQuery.refetchQuery()
  }
  return (
    <Section
      h2={t('dpn.title')}
      size="lg"
      description={dpn.identity ? t('dpn.identity', { identity: dpn.identity }) : t('dpn.noIdentity')}
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
        <ConsumerFacts dpn={dpn} />
        <dt className="text-muted-foreground">{t('dpn.country')}</dt>
        <dd>
          <XSelect
            options={options}
            value={dpn.country ?? ANY_COUNTRY}
            disabled={mutation.isPending}
            onValueChange={(value) => void choose(String(value))}
          />
          {countries.data?.reason && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t('dpn.countriesUnavailable', { reason: countries.data.reason })}
            </p>
          )}
        </dd>
      </dl>
      {dpn.error && <p className="mt-3 text-sm text-warning">{dpn.error}</p>}
      {mutation.isError && <p className="mt-3 text-sm text-destructive">{mutation.error.message}</p>}
    </Section>
  )
}

export const homePage = generalLayout.lets
  .page('/')
  .head({
    title: 'VibeDPN',
    titleTemplate: null,
  })
  .use(redirectUnauthorizedPlugin)
  .with(boxStatusQuery)
  .page(({ data: { status } }) => {
    const summary = summarizeStatus(status)
    const t = useT()
    return (
      <Sections gap="lg">
        <Section h1={t('status.title')}>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={TONE_BADGE[summary.tone]}>
              {summary.tone === 'ok' ? t('status.tone.ok') : t('status.tone.attention')}
            </Badge>
            <p className="font-accent text-lg">{t(summary.headline.key, summary.headline.params)}</p>
          </div>
        </Section>
        <RoutingControls status={status} />
        {status.dpn && <DpnCard dpn={status.dpn} />}
        {status.dpn_countries.map((dpn) => (
          <CountryConsumerCard key={dpn.country} dpn={dpn} />
        ))}
        {status.uplinks
          .filter((uplink) => uplink.enabled)
          .map((uplink) => (
            <UplinkCard key={uplink.name} uplink={uplink} failopen={status.failopen} />
          ))}
      </Sections>
    )
  })
