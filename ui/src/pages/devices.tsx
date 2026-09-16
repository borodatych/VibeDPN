import { useHead } from '@unhead/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { devicePolicySetMutation, devicePolicyUnsetMutation, deviceListQuery } from '@/features/devices/api'
import {
  deviceIdent,
  deviceLabel,
  matchesSearch,
  policyOptions,
  type Device,
  type PolicyChoice,
} from '@/features/devices/shared'
import { boxStatusQuery } from '@/features/status/api'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const DeviceRow = ({ device, enabled }: { device: Device; enabled: { vps: boolean; dpn: boolean; tor: boolean } }) => {
  const setPolicy = devicePolicySetMutation.useMutation()
  const unsetPolicy = devicePolicyUnsetMutation.useMutation()
  const [pendingBlock, setPendingBlock] = useState(false)
  const t = useT()
  const language = useLanguage()
  const [name, setName] = useState(device.name ?? '')
  const ident = deviceIdent(device)
  const busy = setPolicy.isPending || unsetPolicy.isPending
  const error = setPolicy.error ?? unsetPolicy.error

  const apply = async (choice: PolicyChoice) => {
    if (choice === 'mode') {
      await unsetPolicy.mutateAsync({ ident })
    } else {
      await setPolicy.mutateAsync({ ident, policy: choice })
    }
    await deviceListQuery.refetchQuery()
  }

  const rename = async () => {
    if (device.policy === null || !name.trim() || name === device.name) {
      return
    }
    await setPolicy.mutateAsync({ ident, policy: device.policy, name })
    await deviceListQuery.refetchQuery()
  }

  return (
    <TableRow>
      <TableCell>
        <Input
          value={name}
          placeholder={device.hostname ?? deviceLabel(device, t)}
          disabled={device.policy === null || busy}
          title={device.policy === null ? t('devices.nameNeedsPolicy') : undefined}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => void rename()}
          aria-label={t('devices.nameOf', { device: deviceLabel(device, t) })}
        />
      </TableCell>
      <TableCell className="font-mono text-xs">{device.mac ?? t('common.none')}</TableCell>
      <TableCell className="font-mono text-xs">{device.ip ?? t('common.none')}</TableCell>
      <TableCell className="text-sm">
        {device.last_seen ? formatDate(new Date(device.last_seen), 'date-time-nice', language) : t('devices.neverSeen')}
      </TableCell>
      <TableCell>
        {pendingBlock ? (
          <div className="flex items-center gap-2">
            <Button
              variant="destructive"
              size="sm"
              loading={busy}
              onClick={() => {
                setPendingBlock(false)
                void apply('block')
              }}
            >
              {t('devices.cutOff')}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPendingBlock(false)}>
              {t('common.cancel')}
            </Button>
          </div>
        ) : (
          <XSelect
            options={policyOptions(enabled, t)}
            value={device.policy ?? 'mode'}
            disabled={busy}
            onValueChange={(value) => {
              const choice = String(value) as PolicyChoice
              if (choice === 'block') {
                setPendingBlock(true)
              } else {
                void apply(choice)
              }
            }}
          />
        )}
        {error && <p className="mt-1 text-xs text-destructive">{error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

export const devicesPage = generalLayout.lets
  .page('/devices')
  .use(redirectUnauthorizedPlugin)
  .with(deviceListQuery)
  .page(({ data: { devices } }) => {
    const [search, setSearch] = useState('')
    const t = useT()
    useHead({ title: t('nav.devices') })
    // Which uplinks are enabled: until the status arrives, policies through an uplink stay unavailable.
    const uplinks = boxStatusQuery.useQuery().data?.status.uplinks ?? []
    const enabled = {
      vps: uplinks.some((uplink) => uplink.name === 'vps' && uplink.enabled),
      dpn: uplinks.some((uplink) => uplink.name === 'dpn' && uplink.enabled),
      tor: uplinks.some((uplink) => uplink.name === 'tor' && uplink.enabled),
    }
    const shown = devices.filter((device) => matchesSearch(device, search))
    return (
      <Section h1={t('devices.title')} description={t('devices.description')}>
        <Input
          value={search}
          placeholder={t('devices.search')}
          onChange={(event) => setSearch(event.target.value)}
          className="mb-4 max-w-sm"
        />
        {devices.length === 0 ? (
          <p className="text-muted-foreground">{t('devices.empty')}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('devices.column.name')}</TableHead>
                <TableHead>{t('devices.column.mac')}</TableHead>
                <TableHead>{t('devices.column.address')}</TableHead>
                <TableHead>{t('devices.column.lastSeen')}</TableHead>
                <TableHead>{t('devices.column.policy')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((device) => (
                <DeviceRow key={deviceIdent(device)} device={device} enabled={enabled} />
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    )
  })
