import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { XSwitch } from '@/components/ui/switch'
import { humanBytes } from '@/features/node/shared'
import { ProgressBar } from '@/features/torrents/list'
import {
  deviceName,
  dotted,
  speedLimitProblem,
  usedFraction,
  type SpeedSession,
  type StorageView,
} from '@/features/torrents/shared'
import { ApplyLine } from '@/features/uplinks/apply-line'
import { useT } from '@/modules/i18n/use-t'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'

/** What the speed form sends to core: limits in kB/s and whether each is on. */
export type SpeedChange = Pick<
  SpeedSession,
  'speed_limit_down' | 'speed_limit_down_enabled' | 'speed_limit_up' | 'speed_limit_up_enabled'
>

const LimitRow = ({
  label,
  enabled,
  value,
  onEnabled,
  onValue,
}: {
  label: string
  enabled: boolean
  value: string
  onEnabled: (enabled: boolean) => void
  onValue: (value: string) => void
}) => {
  const t = useT()
  const problem = enabled ? speedLimitProblem(value) : null
  return (
    <div className="space-y-1">
      <XSwitch label={label} checked={enabled} onCheckedChange={onEnabled} />
      <div className="flex items-center gap-2">
        <Input
          value={value}
          inputMode="numeric"
          disabled={!enabled}
          aria-label={label}
          aria-invalid={problem !== null}
          className="max-w-32"
          onChange={(event) => onValue(event.target.value.trim())}
        />
        <span className="text-muted-foreground">{t('torrents.speed.unit')}</span>
      </div>
      {problem && <p className="text-destructive">{t('torrents.speed.problem')}</p>}
    </div>
  )
}

/**
 * Limits of the speed of all torrents together: a switch and a number for the way down and for the way up
 *
 * @tags torrents
 */
export const SpeedCard = ({
  session,
  pending,
  error,
  saved,
  onSave,
}: {
  session: SpeedSession
  pending: boolean
  error: string | null
  saved: boolean
  onSave: (change: SpeedChange) => void
}) => {
  const t = useT()
  const [downEnabled, setDownEnabled] = useState(session.speed_limit_down_enabled)
  const [down, setDown] = useState(String(session.speed_limit_down))
  const [upEnabled, setUpEnabled] = useState(session.speed_limit_up_enabled)
  const [up, setUp] = useState(String(session.speed_limit_up))
  const invalid = (downEnabled && speedLimitProblem(down) !== null) || (upEnabled && speedLimitProblem(up) !== null)
  return (
    <Card
      compact
      h2={t('torrents.speed.title')}
      size="sm"
      action={
        <Button
          size="sm"
          disabled={invalid}
          loading={pending}
          onClick={() =>
            onSave({
              speed_limit_down: downEnabled ? Number(down) : session.speed_limit_down,
              speed_limit_down_enabled: downEnabled,
              speed_limit_up: upEnabled ? Number(up) : session.speed_limit_up,
              speed_limit_up_enabled: upEnabled,
            })
          }
        >
          {t('torrents.speed.save')}
        </Button>
      }
    >
      <div className="space-y-4 text-sm">
        <p className="text-muted-foreground">{t('torrents.speed.description')}</p>
        <LimitRow
          label={t('torrents.speed.down')}
          enabled={downEnabled}
          value={down}
          onEnabled={setDownEnabled}
          onValue={setDown}
        />
        <LimitRow
          label={t('torrents.speed.up')}
          enabled={upEnabled}
          value={up}
          onEnabled={setUpEnabled}
          onValue={setUp}
        />
        {error && <p className="text-destructive">{error}</p>}
        {saved && !error && <p className="text-muted-foreground">{t('torrents.speed.saved')}</p>}
      </div>
    </Card>
  )
}

/**
 * Where the torrents are written: the free space of the disk, the drives the host sees, and the choice among them.
 * Choosing a drive restarts the client, so it asks first.
 *
 * @tags torrents
 */
export const StorageCard = ({
  storage,
  choosing,
  refreshing,
  error,
  onChoose,
  onRefresh,
}: {
  storage: StorageView
  choosing: boolean
  refreshing: boolean
  error: string | null
  onChoose: (uuid: string | null) => void
  onRefresh: () => void
}) => {
  const t = useT()
  const used = usedFraction(storage)
  const scanning = storage.state.pending
  return (
    <Card
      compact
      h2={t('torrents.storage.title')}
      size="sm"
      action={
        <Button
          size="sm"
          variant="outline-secondary"
          icon={RefreshCw}
          loading={refreshing || scanning}
          onClick={onRefresh}
        >
          {t('torrents.storage.refresh')}
        </Button>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="space-y-2">
          <p className="text-muted-foreground">{t('torrents.storage.folder')}</p>
          <p className="font-mono text-xs break-all">{storage.download_dir}</p>
          {storage.free_bytes !== null && storage.total_bytes !== null ? (
            <>
              {used !== null && <ProgressBar fraction={used} label={t('torrents.storage.title')} done={used < 0.9} />}
              <p className="tabular-nums">
                {t('torrents.storage.free', {
                  free: humanBytes(storage.free_bytes),
                  total: humanBytes(storage.total_bytes),
                })}
              </p>
            </>
          ) : (
            <p className="text-muted-foreground">{t('torrents.storage.freeUnknown')}</p>
          )}
        </div>
        {storage.storage.configured && !storage.storage.mounted && (
          <p className="text-warning">{t('torrents.storage.missing')}</p>
        )}
        <div className="space-y-2">
          <p className="font-medium">{t('torrents.storage.drives')}</p>
          {storage.devices.length === 0 ? (
            <p className="text-muted-foreground">
              {storage.scanned_at === null ? t('torrents.storage.notScanned') : t('torrents.storage.noDrives')}
            </p>
          ) : (
            <ul className="space-y-2">
              {storage.devices.map((device) => (
                <li
                  key={device.uuid}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium break-all">{deviceName(device)}</p>
                    <p className="text-xs text-muted-foreground">
                      {dotted(device.fstype, humanBytes(device.size), device.device)}
                    </p>
                  </div>
                  {device.current ? (
                    <Badge variant="success">{t('torrents.storage.current')}</Badge>
                  ) : device.supported ? (
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      loading={choosing}
                      confirm={t('torrents.storage.confirmChoose')}
                      onClick={() => onChoose(device.uuid)}
                    >
                      {t('torrents.storage.choose')}
                    </Button>
                  ) : (
                    <Badge variant="secondary">{t('torrents.storage.unsupported')}</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
          {storage.storage.configured && (
            <Button
              size="sm"
              variant="ghost"
              loading={choosing}
              confirm={t('torrents.storage.confirmDefault')}
              onClick={() => onChoose(null)}
            >
              {t('torrents.storage.useDefault')}
            </Button>
          )}
        </div>
        <ApplyLine apply={storage.state} />
        {error && <p className="text-destructive">{error}</p>}
        <p className="text-muted-foreground">{t('torrents.storage.formats')}</p>
      </div>
    </Card>
  )
}
