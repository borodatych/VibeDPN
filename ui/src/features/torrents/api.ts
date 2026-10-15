import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import {
  DETAIL_REFRESH_MS,
  FILE_PRIORITIES,
  LIST_REFRESH_MS,
  MAX_MAGNET_BYTES,
  MAX_SPEED_LIMIT_KBPS,
  MAX_TORRENT_FILE_BYTES,
  SERVICE_OFF_STATUS,
  STORAGE_REFRESH_MS,
  SUBDIR_MAX,
  type SpeedSession,
  type StorageView,
  type TorrentDetail,
  type TorrentList,
} from '@/features/torrents/shared'
import { z } from 'zod'

// 404: the torrent is gone (removed from another screen) — the detail view closes instead of failing.
const NOT_HERE = 404
// base64 grows a third over the bytes
const BASE64_RATIO = 4 / 3
const HASH = /^[0-9a-fA-F]{40}$/

const torrentId = z.string().regex(HASH)

export const torrentsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<TorrentList>('/torrents')
    if (answer.ok) {
      return { off: false as const, reason: null, list: answer.body }
    }
    if (answer.status === SERVICE_OFF_STATUS) {
      return { off: true as const, reason: answer.detail, list: null }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: LIST_REFRESH_MS, staleTime: 0 })

export const torrentDetailQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .input(z.object({ id: torrentId }))
  .loader(async ({ input }) => {
    const answer = await coreFetch<TorrentDetail>(`/torrents/${input.id}`)
    if (answer.ok) {
      return { detail: answer.body }
    }
    if (answer.status === NOT_HERE) {
      return { detail: null }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: DETAIL_REFRESH_MS, staleTime: 0 })

export const torrentAddMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // exactly one of the magnet link and the file, which core checks too
  .input(
    z.object({
      magnet: z.string().max(MAX_MAGNET_BYTES).nullable(),
      torrent: z
        .string()
        .max(Math.ceil(MAX_TORRENT_FILE_BYTES * BASE64_RATIO) + 4)
        .nullable(),
      subdir: z.string().max(SUBDIR_MAX).nullable(),
      paused: z.boolean(),
    }),
  )
  .loader(async ({ input }) => {
    const body = { ...input, subdir: input.subdir?.trim() || null }
    const answer = await coreFetch<{ id: string; name: string; duplicate: boolean }>('/torrents', {
      method: 'POST',
      body,
    })
    if (!answer.ok) {
      throw new AppError(answer.detail, { status: answer.status })
    }
    return answer.body
  })
  .mutation()

export const torrentStartMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ id: torrentId }))
  .loader(async ({ input }) => {
    await coreRequest<null>(`/torrents/${input.id}/start`, { method: 'POST', body: {} })
    return { id: input.id }
  })
  .mutation()

export const torrentStopMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ id: torrentId }))
  .loader(async ({ input }) => {
    await coreRequest<null>(`/torrents/${input.id}/stop`, { method: 'POST', body: {} })
    return { id: input.id }
  })
  .mutation()

export const torrentRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ id: torrentId, data: z.boolean() }))
  .loader(async ({ input }) => {
    await coreRequest<null>(`/torrents/${input.id}?data=${input.data}`, { method: 'DELETE' })
    return { id: input.id }
  })
  .mutation()

export const torrentFilesMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // core refuses an empty list: for Transmission it means «all the files»
  .input(
    z.object({
      id: torrentId,
      indices: z.array(z.number().int().nonnegative()).min(1),
      wanted: z.boolean().nullable(),
      priority: z.enum(FILE_PRIORITIES).nullable(),
    }),
  )
  .loader(async ({ input }) => {
    const { id, ...body } = input
    await coreRequest<null>(`/torrents/${id}/files`, { method: 'PUT', body })
    return { id }
  })
  .mutation()

export const speedSessionQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<SpeedSession>('/torrents/session')
    if (answer.ok) {
      return { session: answer.body }
    }
    if (answer.status === SERVICE_OFF_STATUS) {
      return { session: null }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  // the limits change only from this form; the rates beside them are on the list
  .query({ staleTime: 0 })

export const speedSessionMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      speed_limit_down: z.number().int().min(0).max(MAX_SPEED_LIMIT_KBPS),
      speed_limit_down_enabled: z.boolean(),
      speed_limit_up: z.number().int().min(0).max(MAX_SPEED_LIMIT_KBPS),
      speed_limit_up_enabled: z.boolean(),
    }),
  )
  .loader(async ({ input }) => {
    return { session: await coreRequest<SpeedSession>('/torrents/session', { method: 'PUT', body: input }) }
  })
  .mutation()

export const storageQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<StorageView>('/torrents/storage')
    if (answer.ok) {
      return { storage: answer.body }
    }
    if (answer.status === SERVICE_OFF_STATUS) {
      return { storage: null }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: STORAGE_REFRESH_MS, staleTime: 0 })

/** Asks the host to look at the drives again; the answer is the old list with `state.pending`, the query follows. */
export const storageRefreshMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { storage: await coreRequest<StorageView>('/torrents/storage?refresh=true') }
  })
  .mutation()

export const storageChooseMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // `null`: back to the folder by default
  .input(z.object({ uuid: z.string().min(1).max(64).nullable() }))
  .loader(async ({ input }) => {
    return { storage: await coreRequest<StorageView>('/torrents/storage', { method: 'PUT', body: input }) }
  })
  .mutation()
