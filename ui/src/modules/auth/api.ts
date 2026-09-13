import { root } from '@/lib/root'
import { authServer, getMe } from './server'

/**
 * The current user on the client — our own cached query instead of reading through `authClient`, so every consumer
 * shares one source of truth. Kept never-stale (`staleTime: Infinity`); after a mutation you `refetchQuery` it by hand.
 * Read-only consumers that just want the latest known value (e.g. tracking) call it with `enabled: false` so they
 * mirror the cache without triggering a fetch.
 *
 * @tags auth, query
 * @related getMe
 */
export const getMeQuery = root.lets
  .query()
  .loader(async () => {
    return { me: await getMe() }
  })
  .query({
    // I will modify this query manually, so I wnat it never stale
    staleTime: Infinity,
  })

export const listAccountsQuery = root.lets
  .query()
  .loader(async ({ request }) => {
    return { accounts: await authServer.api.listUserAccounts({ headers: request.original.headers }) }
  })
  .query()

export type AccountsItem = NonNullable<typeof listAccountsQuery.Infer.QueriedData.accounts>[number]
