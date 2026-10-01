import { AppError } from '@/lib/error'
import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import type { BackupsView } from '@/features/backup/shared'
import { z } from 'zod'

// A backup or a restore stops the box for a minute or two; a look every few seconds shows it end.
const REFRESH_MS = 5_000

export const backupsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    let answer
    try {
      answer = await coreFetch<BackupsView>('/backups')
    } catch {
      // core does not answer at all: the box is stopped for a backup or a restore
      return { backups: null, away: true }
    }
    if (!answer.ok) {
      throw new AppError(answer.detail, { status: answer.status })
    }
    return { backups: answer.body, away: false }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const backupMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { backups: await coreRequest<BackupsView>('/backups', { method: 'POST', body: {} }) }
  })
  .mutation()

const archiveInput = z.object({ name: z.string().min(1) })

export const restoreArchiveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(archiveInput)
  .loader(async ({ input }) => {
    const path = `/backups/${encodeURIComponent(input.name)}/restore`
    return { backups: await coreRequest<BackupsView>(path, { method: 'POST', body: {} }) }
  })
  .mutation()

export const deleteArchiveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(archiveInput)
  .loader(async ({ input }) => {
    await coreRequest<null>(`/backups/${encodeURIComponent(input.name)}`, { method: 'DELETE' })
    return { deleted: input.name }
  })
  .mutation()
