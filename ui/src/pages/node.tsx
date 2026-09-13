import { Section, Sections } from '@/components/ui/section'
import { nodeStatsQuery } from '@/features/node/api'
import { formatMyst, humanBytes, shortUptime } from '@/features/node/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <>
    <dt className="text-muted-foreground">{label}</dt>
    <dd>{children}</dd>
  </>
)

export const nodePage = generalLayout.lets
  .page('/node')
  .head('Node')
  .use(redirectUnauthorizedPlugin)
  .with(nodeStatsQuery)
  .page(({ data: { stats, reason } }) => {
    if (!stats) {
      return (
        <Section h1="Node">
          <p className="text-muted-foreground">
            {reason === 'none'
              ? 'This box runs no Mysterium node. The node lives on boxes of role home; a box of role client has its node on the VPS.'
              : `The node does not answer: ${reason}`}
          </p>
        </Section>
      )
    }
    const identity = stats.identity
    const totals = stats.sessions
    return (
      <Sections gap="lg">
        <Section h1="Node" description={`Mysterium ${stats.node_version}, up ${shortUptime(stats.node_uptime)}`}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
            <Row label="Monitoring">{stats.monitoring_status || '—'}</Row>
            <Row label="Services">
              {stats.services.length > 0 ? stats.services.map((item) => `${item.type} ${item.status}`).join(', ') : 'none'}
            </Row>
          </dl>
        </Section>
        <Section h2="Identity and earnings" size="lg">
          {identity ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
              <Row label="Identity">
                <span className="font-mono text-xs break-all">{identity.id}</span>
              </Row>
              <Row label="Registration">{identity.registration_status}</Row>
              <Row label="Balance">{formatMyst(identity.balance_tokens.wei)} MYST</Row>
              <Row label="Earnings">{formatMyst(identity.earnings_tokens.wei)} MYST</Row>
              <Row label="Earnings in total">{formatMyst(identity.earnings_total_tokens.wei)} MYST</Row>
            </dl>
          ) : (
            <p className="text-muted-foreground">No identity yet: the node creates one on its first start.</p>
          )}
        </Section>
        <Section h2="Sessions" size="lg">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
            <Row label="Sessions">
              {totals.count} ({totals.consumers} consumers)
            </Row>
            <Row label="Received">{humanBytes(totals.bytes_received)}</Row>
            <Row label="Sent">{humanBytes(totals.bytes_sent)}</Row>
            <Row label="Earned in sessions">{totals.tokens_myst} MYST</Row>
          </dl>
        </Section>
        {stats.problems.length > 0 && (
          <Section h2="What the node did not answer" size="lg">
            <ul className="list-disc pl-5 text-sm text-warning">
              {stats.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </Section>
        )}
      </Sections>
    )
  })
