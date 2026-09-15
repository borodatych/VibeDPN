import { useHead } from '@unhead/react'
import { Section, Sections } from '@/components/ui/section'
import { nodeStatsQuery } from '@/features/node/api'
import { formatMyst, humanBytes, shortUptime } from '@/features/node/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'

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
    return (
      <Sections gap="lg">
        <Section
          h1={t('node.title')}
          description={t('node.description', { version: stats.node_version, uptime: shortUptime(stats.node_uptime) })}
        >
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
            <Row label={t('node.monitoring')}>{stats.monitoring_status || t('common.none')}</Row>
            <Row label={t('node.services')}>
              {stats.services.length > 0
                ? stats.services.map((item) => `${item.type} ${item.status}`).join(', ')
                : t('node.servicesNone')}
            </Row>
          </dl>
        </Section>
        <Section h2={t('node.identityTitle')} size="lg">
          {identity ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
              <Row label={t('node.identity')}>
                <span className="font-mono text-xs break-all">{identity.id}</span>
              </Row>
              <Row label={t('node.registration')}>{identity.registration_status}</Row>
              <Row label={t('node.balance')}>
                {t('common.myst', { amount: formatMyst(identity.balance_tokens.wei) })}
              </Row>
              <Row label={t('node.earnings')}>
                {t('common.myst', { amount: formatMyst(identity.earnings_tokens.wei) })}
              </Row>
              <Row label={t('node.earningsTotal')}>
                {t('common.myst', { amount: formatMyst(identity.earnings_total_tokens.wei) })}
              </Row>
            </dl>
          ) : (
            <p className="text-muted-foreground">{t('node.noIdentity')}</p>
          )}
        </Section>
        <Section h2={t('node.sessionsTitle')} size="lg">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-accent text-sm">
            <Row label={t('node.sessions')}>
              {t('node.sessionsCount', { count: totals.count, consumers: totals.consumers })}
            </Row>
            <Row label={t('node.received')}>{humanBytes(totals.bytes_received)}</Row>
            <Row label={t('node.sent')}>{humanBytes(totals.bytes_sent)}</Row>
            <Row label={t('node.earnedInSessions')}>{t('common.myst', { amount: totals.tokens_myst })}</Row>
          </dl>
        </Section>
        {stats.problems.length > 0 && (
          <Section h2={t('node.problemsTitle')} size="lg">
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
