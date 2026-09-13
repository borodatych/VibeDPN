import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Section, Sections } from '@/components/ui/section'
import { boxStatusQuery, routingUpdateMutation } from '@/features/status/api'
import { summarizeStatus, type BoxStatus, type UplinkStatus } from '@/features/status/shared'
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

const UplinkCard = ({ uplink, failopen }: { uplink: UplinkStatus; failopen: boolean }) => (
  <Section h2={uplink.name.toUpperCase()} size="lg" description={uplink.in_use ? 'in use' : 'not in use'}>
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
      <dt className="text-muted-foreground">Gateway</dt>
      <dd>{uplink.in_use ? gatewayText(uplink.gateway_alive) : '—'}</dd>
      <dt className="text-muted-foreground">Kill switch</dt>
      <dd>{uplink.in_use ? killSwitchText(uplink, failopen) : '—'}</dd>
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
        {status.uplinks
          .filter((uplink) => uplink.enabled)
          .map((uplink) => (
            <UplinkCard key={uplink.name} uplink={uplink} failopen={status.failopen} />
          ))}
      </Sections>
    )
  })
