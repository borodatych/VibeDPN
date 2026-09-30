import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import { PEER_NAME, trafficSince, type Peer, type PeerFile, type PeerTraffic } from '@/features/peers/shared'
import { z } from 'zod'

// wg-server applies a new peer within seconds, and the handshake shows up soon after
const REFRESH_MS = 5_000
const MS_PER_SECOND = 1000

export const peersQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    // the handshakes are judged against the moment core answered, not the moment of a render
    return { peers: await coreRequest<Peer[]>('/peers'), checkedAt: Date.now() / MS_PER_SECOND }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const peerTrafficQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { totals: await coreRequest<PeerTraffic[]>(`/peers/traffic?since=${trafficSince(new Date())}`) }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const peerAddMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PEER_NAME), tunnel_only: z.boolean() }))
  .loader(async ({ input }) => {
    return { file: await coreRequest<PeerFile>('/peers', { method: 'POST', body: input }) }
  })
  .mutation()

// A mutation, not a query: the file holds the private key, so it is fetched when the owner asks and never cached
export const peerFileMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PEER_NAME) }))
  .loader(async ({ input }) => {
    return { file: await coreRequest<PeerFile>(`/peers/${encodeURIComponent(input.name)}/config`) }
  })
  .mutation()

export const peerRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PEER_NAME) }))
  .loader(async ({ input }) => {
    await coreRequest<null>(`/peers/${encodeURIComponent(input.name)}`, { method: 'DELETE' })
    return { removed: input.name }
  })
  .mutation()
