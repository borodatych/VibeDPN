import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { XSwitch } from '@/components/ui/switch'
import { qrImageSource } from '@/features/access/shared'
import {
  telegramLinkMutation,
  telegramQuery,
  telegramSettingsMutation,
  telegramTestMutation,
  telegramTokenMutation,
} from '@/features/telegram/api'
import {
  alertAfterValid,
  browserTimeZone,
  DIRECT,
  HOURS,
  MAX_ALERT_AFTER_SECONDS,
  MAX_TOKEN_CHARS,
  MIN_ALERT_AFTER_SECONDS,
  tokenProblem,
  WEEKDAYS,
  type TelegramBot,
  type Weekday,
} from '@/features/telegram/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const at = (seconds: number, language: string) => formatDate(new Date(seconds * 1000), 'date-time', language)

// a field left null stays as it is in config.yaml
const UNCHANGED = {
  enabled: null,
  alert_after_seconds: null,
  timezone: null,
  report_enabled: null,
  report_weekday: null,
  report_hour: null,
}

const refresh = async () => {
  await telegramQuery.refetchQuery()
}

const TokenForm = ({ bot }: { bot: TelegramBot }) => {
  const t = useT()
  const save = telegramTokenMutation.useMutation()
  const [token, setToken] = useState('')
  const problem = token ? tokenProblem(token) : null
  const submit = async () => {
    await save.mutateAsync({ token: token.trim() })
    setToken('')
    await refresh()
  }
  return (
    <div className="space-y-2">
      {!bot.token_set && <p>{t('notifications.steps.botfather')}</p>}
      <label className="block space-y-1">
        <span className="block">{t('notifications.token')}</span>
        <Input
          type="password"
          value={token}
          maxLength={MAX_TOKEN_CHARS}
          autoComplete="off"
          spellCheck={false}
          className="max-w-md"
          onChange={(event) => setToken(event.target.value)}
        />
        <span className="block text-xs text-muted-foreground">
          {bot.token_set ? t('notifications.tokenReplace') : t('notifications.tokenHint')}
        </span>
      </label>
      <Button disabled={!token || problem !== null} loading={save.isPending} onClick={() => void submit()}>
        {t('notifications.saveToken')}
      </Button>
      {problem && <p className="text-destructive">{t(`notifications.problem.${problem}`)}</p>}
      {save.isError && <p className="text-destructive">{save.error.message}</p>}
    </div>
  )
}

const LinkOffer = ({ bot }: { bot: TelegramBot }) => {
  const t = useT()
  const language = useLanguage()
  if (bot.link === null || bot.qr_svg === null || bot.link_expires_at === null) {
    return null
  }
  return (
    <div className="space-y-3 rounded-md border p-4">
      <p className="font-semibold">{t('notifications.link.title')}</p>
      <img src={qrImageSource(bot.qr_svg)} alt={t('notifications.link.qrAlt')} className="size-64 max-w-full" />
      <Input
        readOnly
        value={bot.link}
        spellCheck={false}
        className="font-mono text-xs"
        onFocus={(event) => event.target.select()}
      />
      <p className="text-xs text-muted-foreground">
        {t('notifications.link.how', { time: at(bot.link_expires_at, language) })}
      </p>
    </div>
  )
}

const Delivery = ({ bot }: { bot: TelegramBot }) => {
  const t = useT()
  const language = useLanguage()
  if (bot.last_at === null) {
    return null
  }
  let way = t('notifications.way.unknown')
  if (bot.via === DIRECT) {
    way = t('notifications.way.direct')
  } else if (bot.via) {
    way = t('notifications.way.exit', { exit: bot.via })
  }
  const time = at(bot.last_at, language)
  return (
    <div className="space-y-1">
      {bot.last_ok ? (
        <p className="text-muted-foreground">{t('notifications.last.ok', { time, way })}</p>
      ) : (
        <p className="text-destructive">{t('notifications.last.failed', { time, way, message: bot.message })}</p>
      )}
      {bot.waiting > 0 && <p className="text-warning">{t('notifications.waiting', { count: bot.waiting })}</p>}
    </div>
  )
}

const BotCard = ({ bot }: { bot: TelegramBot }) => {
  const t = useT()
  const link = telegramLinkMutation.useMutation()
  const test = telegramTestMutation.useMutation()
  const settings = telegramSettingsMutation.useMutation()
  const offer = async () => {
    await link.mutateAsync({})
    await refresh()
  }
  const toggle = async (enabled: boolean) => {
    await settings.mutateAsync({ ...UNCHANGED, enabled })
    await refresh()
  }
  return (
    <Section h1={t('notifications.title')} description={t('notifications.description')}>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={bot.enabled ? 'success' : 'secondary'}>
            {bot.enabled ? t('notifications.on') : t('notifications.off')}
          </Badge>
          {bot.bot && <span className="font-mono text-xs">{t('notifications.bot', { name: bot.bot })}</span>}
          <span className="text-muted-foreground">
            {bot.linked ? t('notifications.chat', { name: bot.chat }) : t('notifications.noChat')}
          </span>
        </div>
        {bot.token_set && (
          <XSwitch
            checked={bot.enabled}
            disabled={settings.isPending}
            label={t('notifications.enabled')}
            onCheckedChange={(enabled) => void toggle(enabled)}
          />
        )}
        <LinkOffer bot={bot} />
        {bot.token_set && (
          <div className="flex flex-wrap gap-2">
            <Button variant={bot.linked ? 'ghost' : 'default'} loading={link.isPending} onClick={() => void offer()}>
              {bot.linked ? t('notifications.link.other') : t('notifications.link.new')}
            </Button>
            {bot.linked && (
              <Button variant="ghost" loading={test.isPending} onClick={() => void test.mutateAsync({})}>
                {t('notifications.test')}
              </Button>
            )}
          </div>
        )}
        {test.isSuccess && <p className="text-muted-foreground">{t('notifications.testSent')}</p>}
        {test.isError && <p className="text-destructive">{test.error.message}</p>}
        {(link.isError || settings.isError) && (
          <p className="text-destructive">{(link.error ?? settings.error)?.message}</p>
        )}
        <Delivery bot={bot} />
        <TokenForm bot={bot} />
      </div>
    </Section>
  )
}

const SettingsCard = ({ bot }: { bot: TelegramBot }) => {
  const t = useT()
  const save = telegramSettingsMutation.useMutation()
  const [alertAfter, setAlertAfter] = useState(String(bot.alert_after_seconds))
  const [timezone, setTimezone] = useState(bot.timezone)
  const [reportEnabled, setReportEnabled] = useState(bot.report.enabled)
  const [weekday, setWeekday] = useState<Weekday>(bot.report.weekday)
  const [hour, setHour] = useState(bot.report.hour)
  const seconds = Number(alertAfter)
  const browser = browserTimeZone()
  const submit = async () => {
    await save.mutateAsync({
      ...UNCHANGED,
      alert_after_seconds: seconds,
      timezone: timezone.trim(),
      report_enabled: reportEnabled,
      report_weekday: weekday,
      report_hour: hour,
    })
    await refresh()
  }
  return (
    <Section h2={t('notifications.settings.title')} description={t('notifications.settings.description')}>
      <div className="space-y-3 text-sm">
        <label className="block space-y-1">
          <span className="block">{t('notifications.alertAfter')}</span>
          <Input
            type="number"
            min={MIN_ALERT_AFTER_SECONDS}
            max={MAX_ALERT_AFTER_SECONDS}
            value={alertAfter}
            className="max-w-40"
            onChange={(event) => setAlertAfter(event.target.value)}
          />
          <span className="block text-xs text-muted-foreground">{t('notifications.alertAfterHint')}</span>
        </label>
        <label className="block space-y-1">
          <span className="block">{t('notifications.timezone')}</span>
          <Input
            value={timezone}
            maxLength={64}
            spellCheck={false}
            className="max-w-md"
            onChange={(event) => setTimezone(event.target.value)}
          />
          <span className="block text-xs text-muted-foreground">{t('notifications.timezoneHint')}</span>
        </label>
        {browser !== timezone && (
          <Button size="sm" variant="ghost" onClick={() => setTimezone(browser)}>
            {t('notifications.timezoneBrowser', { zone: browser })}
          </Button>
        )}
        <XSwitch checked={reportEnabled} label={t('notifications.report')} onCheckedChange={setReportEnabled} />
        {reportEnabled && (
          <div className="flex flex-wrap items-center gap-3">
            <span>{t('notifications.reportDay')}</span>
            <XSelect
              options={WEEKDAYS.map((day) => ({ value: day, label: t(`notifications.weekday.${day}`) }))}
              value={weekday}
              onValueChange={(value) => setWeekday(String(value) as Weekday)}
            />
            <span>{t('notifications.reportHour')}</span>
            <XSelect
              options={HOURS.map((value) => ({ value, label: `${String(value).padStart(2, '0')}:00` }))}
              value={hour}
              onValueChange={(value) => setHour(Number(value))}
            />
          </div>
        )}
        <Button
          disabled={!alertAfterValid(seconds) || !timezone.trim()}
          loading={save.isPending}
          onClick={() => void submit()}
        >
          {t('notifications.save')}
        </Button>
        {!alertAfterValid(seconds) && <p className="text-destructive">{t('notifications.alertAfterProblem')}</p>}
        {save.isError && <p className="text-destructive">{save.error.message}</p>}
        {save.isSuccess && <p className="text-muted-foreground">{t('notifications.saved')}</p>}
      </div>
    </Section>
  )
}

export const notificationsPage = generalLayout.lets
  .page('/notifications')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.notifications') })
    const data = telegramQuery.useQuery().data
    const bot = data?.bot
    return (
      <Sections gap="lg">
        {data && !bot && (
          <Section h1={t('notifications.title')}>
            <p className="text-sm text-muted-foreground">{data.reason}</p>
          </Section>
        )}
        {bot && <BotCard bot={bot} />}
        {bot && <SettingsCard bot={bot} />}
      </Sections>
    )
  })
