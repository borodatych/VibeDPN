import type { MessageKey, T } from '@/modules/i18n/base'
import { humanBytes } from '@/features/node/shared'
import type { BadgeVariant } from '@/components/ui/badge'

/** The status of a torrent in the list, as core names it (docs/knowledge/transmission/rpc.md: «API ядра»). */
export const TORRENT_STATUSES = [
  'stopped',
  'check_wait',
  'checking',
  'download_wait',
  'downloading',
  'seed_wait',
  'seeding',
] as const
export type TorrentStatus = (typeof TORRENT_STATUSES)[number]

/** `TorrentSummary` of `GET /torrents`; the id is the hash of the torrent, not the number Transmission gave it. */
export type TorrentSummary = {
  id: string
  name: string
  status: TorrentStatus
  /** from 0 to 1 */
  progress: number
  rate_down: number
  rate_up: number
  /** seconds; `null` while unknown */
  eta: number | null
  size: number
  ratio: number | null
  /** the phrase of Transmission, `null` when the torrent has no trouble */
  error: string | null
}

export type TorrentList = { torrents: TorrentSummary[]; rate_down: number; rate_up: number }

export const FILE_PRIORITIES = ['low', 'normal', 'high'] as const
export type FilePriority = (typeof FILE_PRIORITIES)[number]

export type TorrentFile = {
  index: number
  name: string
  size: number
  done: number
  wanted: boolean
  priority: FilePriority
}

export type TorrentPeer = {
  address: string
  client: string
  progress: number
  rate_down: number
  rate_up: number
  flags: string
}

export type TorrentTracker = {
  announce: string
  host: string
  seeders: number | null
  leechers: number | null
  last_announce_ok: boolean
  last_announce_result: string
  /** seconds Unix; 0 or `null` when the tracker has not been asked yet */
  last_announce_time: number | null
}

/** `GET /torrents/{id}`: the summary and what the detail view adds. */
export type TorrentDetail = TorrentSummary & {
  download_dir: string
  files: TorrentFile[]
  peers: TorrentPeer[]
  trackers: TorrentTracker[]
}

/** `GET|PUT /torrents/session`: limits in kB/s, the rates now in B/s. */
export type SpeedSession = {
  speed_limit_down: number
  speed_limit_down_enabled: boolean
  speed_limit_up: number
  speed_limit_up_enabled: boolean
  rate_down?: number
  rate_up?: number
}

export type StorageDevice = {
  uuid: string
  label: string | null
  fstype: string
  size: number
  device: string
  mountpoint: string | null
  /** ext4, exfat or ntfs */
  supported: boolean
  current: boolean
}

/** `GET /torrents/storage`. */
export type StorageView = {
  download_dir: string
  free_bytes: number | null
  total_bytes: number | null
  egress: string
  storage: { configured: boolean; uuid: string | null; mounted: boolean }
  devices: StorageDevice[]
  scanned_at: number | null
  state: { pending: boolean; ok: boolean | null; message: string; finished_at: number | null }
}

// The list is the screen the owner watches while a torrent goes down: a few seconds behind is current enough.
export const LIST_REFRESH_MS = 3_000
// The detail of the open torrent moves with its peers; as often as the list, but only while it is open.
export const DETAIL_REFRESH_MS = 3_000
// Devices change when a drive is plugged in or the host applies a choice: seconds, not milliseconds.
export const STORAGE_REFRESH_MS = 5_000

/** core: the answer for «the service is not on this box» (`torrents.enabled: false`, no container, RPC silent). */
export const SERVICE_OFF_STATUS = 503

/** A `.torrent` is a few tens of KiB; this stops a wrong file from travelling through the panel as base64. */
export const MAX_TORRENT_FILE_BYTES = 4 * 1024 * 1024
/** A magnet link with a long list of trackers is a few KiB. */
export const MAX_MAGNET_BYTES = 8 * 1024
/** Folder names are one name of a file system. */
export const SUBDIR_MAX = 255
/** Limits of the speed form, kB/s: 10 GB/s is above any link of a box. */
export const MAX_SPEED_LIMIT_KBPS = 10_000_000

const NONE = '—'
const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3_600
const SECONDS_PER_DAY = 86_400

/** The filters of the list, in the order of the buttons. */
export const TORRENT_FILTERS = ['all', 'downloading', 'seeding', 'paused', 'error'] as const
export type TorrentFilter = (typeof TORRENT_FILTERS)[number]

const DOWNLOADING: readonly TorrentStatus[] = ['check_wait', 'checking', 'download_wait', 'downloading']
const SEEDING: readonly TorrentStatus[] = ['seed_wait', 'seeding']

/**
 * Whether a torrent belongs to a filter: a torrent with trouble is also in the filter of its status, so «downloading»
 * still counts the one that stalled
 *
 * @tags torrents
 */
export const matchesFilter = (torrent: TorrentSummary, filter: TorrentFilter): boolean => {
  switch (filter) {
    case 'all':
      return true
    case 'downloading':
      return DOWNLOADING.includes(torrent.status)
    case 'seeding':
      return SEEDING.includes(torrent.status)
    case 'paused':
      return torrent.status === 'stopped'
    case 'error':
      return torrent.error !== null
  }
}

export const countByFilter = (torrents: readonly TorrentSummary[]): Record<TorrentFilter, number> => {
  const counts = Object.fromEntries(TORRENT_FILTERS.map((filter) => [filter, 0])) as Record<TorrentFilter, number>
  for (const torrent of torrents) {
    for (const filter of TORRENT_FILTERS) {
      if (matchesFilter(torrent, filter)) {
        counts[filter] += 1
      }
    }
  }
  return counts
}

/** `1048576` → `1.0 MiB/s`; nothing flowing is a dash, not «0 B/s» repeated on every row. */
export const formatRate = (bytesPerSecond: number): string =>
  bytesPerSecond > 0 ? `${humanBytes(bytesPerSecond)}/s` : NONE

/** The two largest units of the time left: `3h 20m`; unknown (`null`) is a dash. */
export const formatEta = (seconds: number | null, t: T): string => {
  if (seconds === null || seconds < 0) {
    return NONE
  }
  const whole = Math.floor(seconds)
  if (whole < SECONDS_PER_MINUTE) {
    return t('torrents.eta.seconds', { s: whole })
  }
  if (whole < SECONDS_PER_HOUR) {
    return t('torrents.eta.minutes', { m: Math.floor(whole / SECONDS_PER_MINUTE) })
  }
  if (whole < SECONDS_PER_DAY) {
    return t('torrents.eta.hours', {
      h: Math.floor(whole / SECONDS_PER_HOUR),
      m: Math.floor((whole % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE),
    })
  }
  return t('torrents.eta.days', {
    d: Math.floor(whole / SECONDS_PER_DAY),
    h: Math.floor((whole % SECONDS_PER_DAY) / SECONDS_PER_HOUR),
  })
}

/** `0.4237` → `42.4%`; out of range is clamped, so a bar never leaves its track. */
export const formatPercent = (fraction: number): string => `${(clampFraction(fraction) * 100).toFixed(1)}%`

/** The width of a progress bar, 0–100. */
export const barPercent = (fraction: number): number => Math.round(clampFraction(fraction) * 100)

const clampFraction = (fraction: number) => Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0))

/** The ratio of uploaded to downloaded, two digits; unknown is a dash. */
export const formatRatio = (ratio: number | null): string => (ratio === null ? NONE : ratio.toFixed(2))

/** Seeders and leechers of a tracker; a tracker that has not answered gives a dash. */
export const formatCount = (count: number | null): string => (count === null ? NONE : String(count))

const STATUS_KEYS: Record<TorrentStatus, MessageKey> = {
  stopped: 'torrents.status.stopped',
  check_wait: 'torrents.status.check_wait',
  checking: 'torrents.status.checking',
  download_wait: 'torrents.status.download_wait',
  downloading: 'torrents.status.downloading',
  seed_wait: 'torrents.status.seed_wait',
  seeding: 'torrents.status.seeding',
}

/** The key of the word for a status; a torrent with trouble is named by the trouble, not by what it was doing. */
export const statusKey = (torrent: TorrentSummary): MessageKey =>
  torrent.error === null ? STATUS_KEYS[torrent.status] : 'torrents.status.error'

export const statusVariant = (torrent: TorrentSummary): BadgeVariant => {
  if (torrent.error !== null) {
    return 'destructive'
  }
  if (DOWNLOADING.includes(torrent.status)) {
    return torrent.status === 'downloading' ? 'info' : 'warning'
  }
  if (SEEDING.includes(torrent.status)) {
    return 'success'
  }
  return 'secondary'
}

/** A torrent that runs can be stopped, a stopped one started: the button of a row. */
export const isRunning = (torrent: TorrentSummary): boolean => torrent.status !== 'stopped'

/** Why this text cannot be a magnet link yet; `null` when it can. */
export const magnetProblem = (text: string): 'empty' | 'format' | 'long' | null => {
  const link = text.trim()
  if (link === '') {
    return 'empty'
  }
  if (link.length > MAX_MAGNET_BYTES) {
    return 'long'
  }
  return /^magnet:\?.*xt=urn:bt(ih|mh):[0-9a-zA-Z]+/i.test(link) ? null : 'format'
}

/** Why this text cannot be a subfolder; `null` when it can, and an empty one is the download folder itself. */
export const subdirProblem = (text: string): 'format' | null => {
  const name = text.trim()
  if (name === '') {
    return null
  }
  const bad = name === '.' || name === '..' || name.length > SUBDIR_MAX || /[/\\\0]/.test(name)
  return bad ? 'format' : null
}

/** Why this file cannot be a torrent to add; `null` when it can. */
export const torrentFileProblem = (file: { name: string; size: number }): 'extension' | 'large' | 'empty' | null => {
  if (!file.name.toLowerCase().endsWith('.torrent')) {
    return 'extension'
  }
  if (file.size === 0) {
    return 'empty'
  }
  return file.size > MAX_TORRENT_FILE_BYTES ? 'large' : null
}

const BASE64_CHUNK = 0x8000

/** The body of a `.torrent` as base64, in chunks: one `apply` over a large array overflows the stack. */
export const bytesToBase64 = (bytes: Uint8Array): string => {
  let binary = ''
  for (let start = 0; start < bytes.length; start += BASE64_CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(start, start + BASE64_CHUNK))
  }
  return btoa(binary)
}

/** Why this text cannot be a speed limit; `null` when it can. */
export const speedLimitProblem = (text: string): 'format' | null => {
  if (!/^\d{1,8}$/.test(text.trim())) {
    return 'format'
  }
  return Number(text) > MAX_SPEED_LIMIT_KBPS ? 'format' : null
}

/** The part of a file already on disk; a file without size is whole. */
export const fileFraction = (file: TorrentFile): number => (file.size > 0 ? file.done / file.size : 1)

/** The indices of the files in a selection, sorted: `PUT /torrents/{id}/files` takes at least one. */
export const sortedIndices = (selected: ReadonlySet<number>): number[] => [...selected].sort((a, b) => a - b)

/** The name of a drive for a list: its label, else its device. */
export const deviceName = (device: StorageDevice): string => device.label?.trim() || device.device

/** How full the disk is, 0–1; unknown until Transmission answers. */
export const usedFraction = (storage: Pick<StorageView, 'free_bytes' | 'total_bytes'>): number | null =>
  storage.free_bytes === null || storage.total_bytes === null || storage.total_bytes <= 0
    ? null
    : 1 - storage.free_bytes / storage.total_bytes

/** Parts of one line of small print, set apart by a middle dot: `ext4 · 1.0 TiB · /dev/sda1`. */
export const dotted = (...parts: readonly (string | number)[]): string => parts.join(' · ')

/** What a magnet link looks like, for the empty field. */
export const MAGNET_EXAMPLE = 'magnet:?xt=urn:btih:…'
