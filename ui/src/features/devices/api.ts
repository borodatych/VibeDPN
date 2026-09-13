import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import { DEVICE_POLICIES, type Device } from '@/features/devices/shared'
import { z } from 'zod'

// Core refreshes its neighbour table every 30 s; polling faster shows nothing new.
const DEVICES_REFRESH_MS = 30_000
const DEVICE_NAME_MAX = 64

const devicePath = (ident: string) => `/devices/${encodeURIComponent(ident)}`

export const deviceListQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { devices: await coreRequest<Device[]>('/devices') }
  })
  .query({
    refetchInterval: DEVICES_REFRESH_MS,
    staleTime: 0,
  })

export const devicePolicySetMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      ident: z.string().min(1),
      policy: z.enum(DEVICE_POLICIES),
      name: z.string().trim().min(1).max(DEVICE_NAME_MAX).optional(),
    }),
  )
  .loader(async ({ input }) => {
    await coreRequest(devicePath(input.ident), {
      method: 'PUT',
      body: { policy: input.policy, ...(input.name ? { name: input.name } : {}) },
    })
    return { ok: true }
  })
  .mutation()

export const devicePolicyUnsetMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ ident: z.string().min(1) }))
  .loader(async ({ input }) => {
    await coreRequest(devicePath(input.ident), { method: 'DELETE' })
    return { ok: true }
  })
  .mutation()
