import { useHead } from '@unhead/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { eventListQuery, wifiClientsQuery } from '@/features/events/api'
import { deviceName, DROPS_WINDOW_HOURS, durationText, wifiDrops } from '@/features/events/shared'
import { networkQuery, networkUpdateMutation, wifiPassphraseMutation } from '@/features/network/api'
import {
  currentChoice,
  lanOptions,
  PASSPHRASE_MAX,
  PASSPHRASE_MIN,
  passphraseProblem,
  SIDECAR,
} from '@/features/network/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'
import { useState } from 'react'

/** A new Wi-Fi password: core stores it and the running access point takes it, dropping every device. */
const PassphraseForm = () => {
  const t = useT()
  const save = wifiPassphraseMutation.useMutation()
  const [value, setValue] = useState('')
  const [repeat, setRepeat] = useState('')
  const problem = value || repeat ? passphraseProblem(value, repeat) : null
  const limits = { min: PASSPHRASE_MIN, max: PASSPHRASE_MAX }
  const submit = async () => {
    await save.mutateAsync({ passphrase: value })
    setValue('')
    setRepeat('')
  }
  const result = save.data?.wifi
  return (
    <div className="mt-6 space-y-2">
      <p className="font-accent text-sm text-muted-foreground">{t('wifi.passphrase.title')}</p>
      <div className="flex flex-wrap gap-2">
        <Input
          type="password"
          value={value}
          maxLength={PASSPHRASE_MAX}
          autoComplete="new-password"
          spellCheck={false}
          placeholder={t('wifi.passphrase.new')}
          aria-label={t('wifi.passphrase.new')}
          className="max-w-xs"
          onChange={(event) => setValue(event.target.value)}
        />
        <Input
          type="password"
          value={repeat}
          maxLength={PASSPHRASE_MAX}
          autoComplete="new-password"
          spellCheck={false}
          placeholder={t('wifi.passphrase.repeat')}
          aria-label={t('wifi.passphrase.repeat')}
          className="max-w-xs"
          onChange={(event) => setRepeat(event.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">{t('wifi.passphrase.hint', limits)}</p>
      <Button
        disabled={!value || problem !== null}
        loading={save.isPending}
        confirm={t('wifi.passphrase.confirm')}
        onClick={() => void submit()}
      >
        {t('wifi.passphrase.save')}
      </Button>
      {problem && <p className="text-sm text-destructive">{t(`wifi.passphrase.problem.${problem}`, limits)}</p>}
      {save.isError && <p className="text-sm text-destructive">{save.error.message}</p>}
      {result && (
        <p className={result.result === 'pending' ? 'text-sm text-warning' : 'text-sm'}>
          {t(`wifi.passphrase.result.${result.result}`, { error: result.error })}
        </p>
      )}
    </div>
  )
}

/** Who is on the access point now and how often it dropped them; nothing on a box without Wi-Fi. */
const WifiSection = () => {
  const t = useT()
  const wifi = wifiClientsQuery.useQuery().data
  const events = eventListQuery.useQuery({ kind: 'wifi', hours: DROPS_WINDOW_HOURS }).data?.events ?? []
  if (!wifi?.available) {
    return null
  }
  return (
    <Section h2={t('wifi.title')} description={t('wifi.description')}>
      <p className="text-sm">{t('wifi.drops', { count: wifiDrops(events) })}</p>
      {wifi.reason && <p className="mt-2 text-sm text-warning">{wifi.reason}</p>}
      {wifi.clients.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t('wifi.empty')}</p>
      ) : (
        <Table className="mt-3">
          <TableHeader>
            <TableRow>
              <TableHead>{t('wifi.column.device')}</TableHead>
              <TableHead>{t('wifi.column.connected')}</TableHead>
              <TableHead>{t('wifi.column.signal')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {wifi.clients.map((client) => (
              <TableRow key={client.mac}>
                <TableCell>
                  <div>{deviceName(client.name, t)}</div>
                  <div className="font-mono text-xs text-muted-foreground">{client.mac}</div>
                </TableCell>
                <TableCell>{durationText(client.connected_seconds, t)}</TableCell>
                <TableCell>
                  {client.signal_dbm === null ? t('wifi.signalUnknown') : t('wifi.signal', { dbm: client.signal_dbm })}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <PassphraseForm />
    </Section>
  )
}

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
      <Sections gap="lg">
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
              {t('network.saved', { command: 'sudo vibedpn up', address: network.lan_address })}
            </p>
          )}
        </Section>
        <WifiSection />
      </Sections>
    )
  })
