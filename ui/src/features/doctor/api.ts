import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import type { DoctorView } from '@/features/doctor/shared'
import { z } from 'zod'

// A check takes seconds, with the exit addresses up to a minute; a look every few seconds shows it end.
const REFRESH_MS = 5_000

export const doctorQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { doctor: await coreRequest<DoctorView>('/doctor') }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const doctorMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ network: z.boolean() }))
  .loader(async ({ input }) => {
    return { doctor: await coreRequest<DoctorView>('/doctor', { method: 'POST', body: input }) }
  })
  .mutation()
