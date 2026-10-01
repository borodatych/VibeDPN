import { useHead } from '@unhead/react'
import { PageTitle } from '@/components/blocks/page-title'
import { Card } from '@/components/ui/card'
import { Section, Sections } from '@/components/ui/section'
import { nodeStatsQuery } from '@/features/node/api'
import { formatMyst, humanBytes, shortUptime } from '@/features/node/shared'
import { LogsCard } from '@/features/logs/card'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'

/** A number of the node in a tile: the label small above, the value large */
const Tile = ({ label, value }: { label: string; value: string }) => (
  <div data-tile className="rounded-xl border border-border bg-card px-4 py-3">
    <p className="text-xs text-muted-foreground">{label}</p>
    <p className="mt-1 font-accent text-lg font-semibold break-words">{value}</p>
  </div>
)

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <>
    <dt className="text-muted-foreground">{label}</dt>
    <dd>{children}</dd>
  </>
)

export const nodePage = generalLayout.lets
  .page('/node')
  .use(redirectUnauthorizedPlugin)
  .with(nodeStatsQuery)
  .page(({ data: { stats, reason } }) => {
    const t = useT()
    useHead({ title: t('nav.node') })
    if (!stats) {
      return (
        <Section h1={t('node.title')}>
          <p className="text-muted-foreground">{reason === 'none' ? t('node.none') : t('node.silent', { reason })}</p>
        </Section>
      )
    }
    const identity = stats.identity
    const totals = stats.sessions
    const myst = (wei: string) => t('common.myst', { amount: formatMyst(wei) })
    return (
      <Sections gap="lg">
        <PageTitle
          title={t('node.title')}
          description={t('node.description', { version: stats.node_version, uptime: shortUptime(stats.node_uptime) })}
        />
        {/* the numbers the owner opens the page for, first; the details of the node in the cards below */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Tile label={t('node.balance')} value={identity ? myst(identity.balance_tokens.wei) : t('common.none')} />
          <Tile
            label={t('node.earningsTotal')}
            value={identity ? myst(identity.earnings_total_tokens.wei) : t('common.none')}
          />
          <Tile
            label={t('node.sessions')}
            value={t('node.sessionsCount', { count: totals.count, consumers: totals.consumers })}
          />
          <Tile label={t('node.sent')} value={humanBytes(totals.bytes_sent)} />
        </div>
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <Card compact h2={t('node.title')} size="sm">
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 font-accent text-sm">
              <Row label={t('node.monitoring')}>{stats.monitoring_status || t('common.none')}</Row>
              <Row label={t('node.services')}>
                {stats.services.length > 0
                  ? stats.services.map((item) => `${item.type} ${item.status}`).join(', ')
                  : t('node.servicesNone')}
              </Row>
              <Row label={t('node.received')}>{humanBytes(totals.bytes_received)}</Row>
              <Row label={t('node.earnedInSessions')}>{t('common.myst', { amount: totals.tokens_myst })}</Row>
            </dl>
          </Card>
          <Card compact h2={t('node.identityTitle')} size="sm">
            {identity ? (
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 font-accent text-sm">
                <Row label={t('node.identity')}>
                  <span className="font-mono text-xs break-all">{identity.id}</span>
                </Row>
                <Row label={t('node.registration')}>{identity.registration_status}</Row>
                <Row label={t('node.earnings')}>{myst(identity.earnings_tokens.wei)}</Row>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">{t('node.noIdentity')}</p>
            )}
          </Card>
        </div>
        {stats.problems.length > 0 && (
          <Card compact h2={t('node.problemsTitle')} size="sm">
            <ul className="list-disc pl-5 text-sm text-warning">
              {stats.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </Card>
        )}
        <LogsCard scope="node" />
      </Sections>
    )
  })
