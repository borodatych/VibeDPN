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
import { formatDate } from '@/utils/date'

const TONE_BADGE = { ok: 'success', warning: 'warning', danger: 'destructive' } as const

const gatewayText = (alive: boolean | null) =>
  alive === null ? 'not probed yet' : alive ? 'answers' : 'does not answer'

const killSwitchText = (uplink: UplinkStatus, failopen: boolean) => {
  if (failopen) {
    return 'off (failopen: traffic goes direct when the gateway is silent)'
  }
  if (uplink.kill_switch_route === null) {
    return 'cannot read the route table'
  }
  return uplink.kill_switch_route ? 'armed' : 'missing — run vibedpn doctor'
}

const VpsLanAccess = ({ allowed }: { allowed: boolean }) => {
  const mutation = vpsLanAccessMutation.useMutation()
  const change = async (next: boolean) => {
    await mutation.mutateAsync({ allowed: next })
    await boxStatusQuery.refetchQuery()
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span>{allowed ? 'open' : 'closed'}</span>
      {allowed ? (
        <Button variant="outline-secondary" size="sm" loading={mutation.isPending} onClick={() => void change(false)}>
          Close to the LAN
        </Button>
      ) : (
        <Button
          variant="outline-secondary"
          size="sm"
          loading={mutation.isPending}
          confirm="Let every LAN device reach the node panel and the core API of the VPS?"
          onClick={() => void change(true)}
        >
          Open to the LAN
        </Button>
      )}
      {mutation.isError && <span className="text-xs text-destructive">{mutation.error.message}</span>}
    </div>
  )
}

const UplinkCard = ({ uplink, failopen }: { uplink: UplinkStatus; failopen: boolean }) => (
  <Section h2={uplink.name.toUpperCase()} size="lg" description={uplink.in_use ? 'in use' : 'not in use'}>
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
      <dt className="text-muted-foreground">Gateway</dt>
      <dd>{uplink.in_use ? gatewayText(uplink.gateway_alive) : '—'}</dd>
      <dt className="text-muted-foreground">Kill switch</dt>
      <dd>{uplink.in_use ? killSwitchText(uplink, failopen) : '—'}</dd>
      {uplink.lan_access !== null && (
        <>
          <dt className="text-muted-foreground">Node panel and API of the VPS for the LAN</dt>
          <dd>
            <VpsLanAccess allowed={uplink.lan_access} />
          </dd>
        </>
      )}
      <dt className="text-muted-foreground">Checked</dt>
      <dd>{uplink.checked_at ? formatDate(new Date(uplink.checked_at), 'date-time') : '—'}</dd>
      {uplink.error && (
        <>
          <dt className="text-muted-foreground">Error</dt>
          <dd className="text-destructive">{uplink.error}</dd>
        </>
      )}
    </dl>
  </Section>
)

const RoutingControls = ({ status }: { status: BoxStatus }) => {
  const mutation = routingUpdateMutation.useMutation()
  const change = async (input: { mode?: 'off' | 'full'; default_upstream?: 'vps' | 'dpn' }) => {
    await mutation.mutateAsync(input)
    await boxStatusQuery.refetchQuery()
  }
  const enabled = status.uplinks.filter((uplink) => uplink.enabled)
  return (
    <Section h2="Routing" size="lg" description={`failopen: ${status.failopen ? 'on' : 'off'}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-accent text-sm text-muted-foreground">Mode</span>
        <Button
          variant={status.mode === 'off' ? 'default' : 'outline-secondary'}
          disabled={status.mode === 'off'}
          loading={mutation.isPending}
          onClick={() => void change({ mode: 'off' })}
        >
          Off — LAN direct
        </Button>
        <Button
          variant={status.mode === 'full' ? 'default' : 'outline-secondary'}
          disabled={status.mode === 'full'}
          loading={mutation.isPending}
          confirm={`Route the whole LAN through ${status.default_upstream}?`}
          onClick={() => void change({ mode: 'full' })}
        >
          Full — via uplink
        </Button>
      </div>
      {enabled.length > 1 && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="font-accent text-sm text-muted-foreground">Uplink</span>
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
        <p className="mt-3 text-sm text-warning">AdGuard did not answer: DNS follows the mode at the next start of core.</p>
      )}
    </Section>
  )
}

const ANY_COUNTRY = 'any'

const DpnCard = ({ dpn }: { dpn: DpnStatus }) => {
  const countries = dpnCountriesQuery.useQuery()
  const mutation = dpnCountryMutation.useMutation()
  const offers = countries.data?.countries ?? []
  const options = [
    { value: ANY_COUNTRY, label: 'Any country' },
    ...offers.map((offer) => ({
      value: offer.country,
      label: `${offer.country} · ${offer.nodes} nodes · from ${formatMyst(offer.min_per_gib_wei)} MYST/GiB`,
    })),
  ]
  const choose = async (value: string) => {
    await mutation.mutateAsync({ country: value === ANY_COUNTRY ? null : value })
    await boxStatusQuery.refetchQuery()
  }
  return (
    <Section h2="Mysterium exit (dpn)" size="lg" description={dpn.identity ? `identity ${dpn.identity}` : 'no identity yet'}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
        <dt className="text-muted-foreground">Registration</dt>
        <dd>{dpn.registration}</dd>
        <dt className="text-muted-foreground">Connection</dt>
        <dd>{dpn.connection}</dd>
        <dt className="text-muted-foreground">Balance</dt>
        <dd>{formatMyst(dpn.balance_wei)} MYST</dd>
        <dt className="text-muted-foreground">Top up (MYST on Polygon)</dt>
        <dd className="font-mono text-xs break-all">{dpn.channel_address || '—'}</dd>
        <dt className="text-muted-foreground">Country</dt>
        <dd>
          <XSelect
            options={options}
            value={dpn.country ?? ANY_COUNTRY}
            disabled={mutation.isPending}
            onValueChange={(value) => void choose(String(value))}
          />
          {countries.data?.reason && (
            <p className="mt-1 text-xs text-muted-foreground">Countries unavailable: {countries.data.reason}</p>
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
    return (
      <Sections gap="lg">
        <Section h1="Box status">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={TONE_BADGE[summary.tone]}>{summary.tone === 'ok' ? 'OK' : 'Attention'}</Badge>
            <p className="font-accent text-lg">{summary.headline}</p>
          </div>
        </Section>
        <RoutingControls status={status} />
        {status.dpn && <DpnCard dpn={status.dpn} />}
        {status.uplinks
          .filter((uplink) => uplink.enabled)
          .map((uplink) => (
            <UplinkCard key={uplink.name} uplink={uplink} failopen={status.failopen} />
          ))}
      </Sections>
    )
  })
