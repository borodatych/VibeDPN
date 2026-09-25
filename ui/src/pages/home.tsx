import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Section, Sections } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import {
  boxStatusQuery,
  dpnCountriesQuery,
  dpnCountryMutation,
  dpnRegisterMutation,
  dpnRegistrationQuery,
  routingUpdateMutation,
  vpsLanAccessMutation,
} from '@/features/status/api'
import { formatMyst } from '@/features/node/shared'
import { REGISTERED } from '@/features/status/shared'
import {
  raiseInChain,
  routableUplinks,
  summarizeStatus,
  type BoxStatus,
  type DpnStatus,
  type UplinkStatus,
} from '@/features/status/shared'
import { eventListQuery } from '@/features/events/api'
import { DROPS_WINDOW_HOURS, WIFI_DROPS_WARNING, wifiDrops } from '@/features/events/shared'
import { UpdateCard } from '@/features/update/card'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { ArrowUpIcon, XIcon } from 'lucide-react'

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

const exitText = (uplink: UplinkStatus, t: T) => {
  if (uplink.exit_through === null) {
    return t('uplink.exit.none')
  }
  return uplink.exit_through === uplink.name ? t('uplink.exit.own') : uplink.exit_through.toUpperCase()
}

const uplinkRole = (uplink: UplinkStatus, t: T) => {
  if (uplink.in_use) {
    return t('uplink.inUse')
  }
  return uplink.fallback ? t('uplink.inFallback') : t('uplink.notInUse')
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
  const watched = uplink.in_use || uplink.fallback
  return (
    <Section h2={uplink.name.toUpperCase()} size="lg" description={uplinkRole(uplink, t)}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
        <dt className="text-muted-foreground">{t('uplink.gateway')}</dt>
        <dd>{watched ? gatewayText(uplink.gateway_alive, t) : t('common.none')}</dd>
        {uplink.in_use && (
          <>
            <dt className="text-muted-foreground">{t('uplink.exit')}</dt>
            <dd>{exitText(uplink, t)}</dd>
          </>
        )}
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
  const change = async (input: { mode?: 'off' | 'full'; default_upstream?: string; fallback?: string[] }) => {
    await mutation.mutateAsync(input)
    await boxStatusQuery.refetchQuery()
  }
  const enabled = routableUplinks(status)
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
          {enabled.map((name) => (
            <Button
              key={name}
              variant={status.default_upstream === name ? 'default' : 'outline-secondary'}
              disabled={status.default_upstream === name}
              loading={mutation.isPending}
              onClick={() => void change({ default_upstream: name })}
            >
              {name.toUpperCase()}
            </Button>
          ))}
        </div>
      )}
      {enabled.length > 1 && (
        <FallbackChain
          chain={status.fallback}
          candidates={enabled.filter((name) => !status.fallback.includes(name))}
          pending={mutation.isPending}
          onChange={(fallback) => void change({ fallback })}
        />
      )}
      {mutation.isError && <p className="mt-3 text-sm text-destructive">{mutation.error.message}</p>}
      {mutation.data?.routing.adguard === 'pending' && (
        <p className="mt-3 text-sm text-warning">{t('routing.adguardPending')}</p>
      )}
    </Section>
  )
}

const FallbackChain = ({
  chain,
  candidates,
  pending,
  onChange,
}: {
  chain: string[]
  candidates: string[]
  pending: boolean
  onChange: (chain: string[]) => void
}) => {
  const t = useT()
  return (
    <div className="mt-4 space-y-2">
      <p className="font-accent text-sm text-muted-foreground">{t('routing.fallback.title')}</p>
      <p className="text-sm text-muted-foreground">{t('routing.fallback.hint')}</p>
      {chain.length === 0 ? (
        <p className="text-sm">{t('routing.fallback.empty')}</p>
      ) : (
        <ol className="space-y-1">
          {chain.map((name, index) => (
            <li key={name} className="flex items-center gap-2 font-accent text-sm">
              <span className="w-6 text-muted-foreground">{index + 1}</span>
              <span className="min-w-24">{name.toUpperCase()}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                icon={ArrowUpIcon}
                aria-label={t('routing.fallback.up', { uplink: name })}
                hint={t('routing.fallback.up', { uplink: name })}
                disabled={index === 0 || pending}
                onClick={() => onChange(raiseInChain(chain, name))}
              />
              <Button
                variant="ghost"
                size="icon-sm"
                icon={XIcon}
                aria-label={t('routing.fallback.remove', { uplink: name })}
                hint={t('routing.fallback.remove', { uplink: name })}
                disabled={pending}
                onClick={() => onChange(chain.filter((item) => item !== name))}
              />
            </li>
          ))}
        </ol>
      )}
      {candidates.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-accent text-sm text-muted-foreground">{t('routing.fallback.add')}</span>
          {candidates.map((name) => (
            <Button
              key={name}
              variant="outline-secondary"
              size="sm"
              loading={pending}
              onClick={() => onChange([...chain, name])}
            >
              {name.toUpperCase()}
            </Button>
          ))}
        </div>
      )}
    </div>
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

/** The one button on this box that may spend money: the box never registers by itself (decision 4). */
const RegisterIdentity = ({ dpn }: { dpn: DpnStatus }) => {
  const offer = dpnRegistrationQuery.useQuery().data?.registration
  const start = dpnRegisterMutation.useMutation()
  const t = useT()
  if (!dpn.identity || dpn.registration === REGISTERED) {
    return null
  }
  const go = async () => {
    await start.mutateAsync({})
    await boxStatusQuery.refetchQuery()
    await dpnRegistrationQuery.refetchQuery()
  }
  const price = offer?.free ? t('dpn.register.free') : t('dpn.register.fee', { fee: formatMyst(offer?.fee_wei ?? '0') })
  return (
    <div className="mt-3 space-y-2 text-sm">
      <p className="text-muted-foreground">{price}</p>
      {offer && !offer.free && !offer.affordable && (
        <p className="text-warning">{t('dpn.register.poor', { address: offer.channel_address })}</p>
      )}
      <Button
        size="sm"
        disabled={!offer || (!offer.free && !offer.affordable)}
        loading={start.isPending}
        confirm={offer?.free ? undefined : t('dpn.register.confirm', { fee: formatMyst(offer?.fee_wei ?? '0') })}
        onClick={() => void go()}
      >
        {t('dpn.register.button')}
      </Button>
      {start.isError && <p className="text-destructive">{start.error.message}</p>}
      {start.isSuccess && <p className="text-muted-foreground">{t('dpn.register.started')}</p>}
    </div>
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
      <RegisterIdentity dpn={dpn} />
      {dpn.error && <p className="mt-3 text-sm text-warning">{dpn.error}</p>}
      {mutation.isError && <p className="mt-3 text-sm text-destructive">{mutation.error.message}</p>}
    </Section>
  )
}

/** Frequent Wi-Fi drops are worth a line under the headline; a few are normal and stay in the journal. */
const WifiDropsNotice = () => {
  const t = useT()
  const events = eventListQuery.useQuery({ kind: 'wifi', hours: DROPS_WINDOW_HOURS }).data?.events ?? []
  const drops = wifiDrops(events)
  if (drops < WIFI_DROPS_WARNING) {
    return null
  }
  return <p className="mt-3 text-sm text-warning">{t('status.wifiDrops', { count: drops })}</p>
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
          <WifiDropsNotice />
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
        <UpdateCard />
      </Sections>
    )
  })
