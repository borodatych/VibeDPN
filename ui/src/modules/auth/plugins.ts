import { AppError } from '@/lib/error'
import { redirect } from '@/lib/navigation'
import { getMe } from '@/modules/auth/server'
import { Point0 } from '@point0/core'
import { getMeQuery } from '@/modules/auth/api'

/**
 * Loads `me` into ctx/props from the current session and prefetches `getMeQuery` for the page.
 *
 * Building block for the gating plugins below; rarely used directly. Use one of `authorizedOnlyPlugin`,
 * `redirectUnauthorizedPlugin`, `redirectAuthorizedPlugin`, or `adminOnlyPlugin` instead.
 *
 * @tags auth, plugin
 */
export const mePlugin = Point0.lets
  .plugin()
  .onPrefetchPage(async () => {
    await getMeQuery.prefetchQuery()
  })
  .ctx(async ({ request }) => {
    return { me: await getMe({ request }) }
  })
  .with(({ resolve }) => {
    // I can do just return getMeQuery.useQuery(), but then it will come to queries,
    // but I want it come only to props, so I return it from with fn

    // we can do this
    // const query = getMeQuery.useQuery()
    // if (query.isError) {
    //   return query.error
    // }
    // if (query.isLoading || !query.data) {
    //   return 'loading'
    // }
    // const me = query.data.me
    // return { me }

    // or this, it is same
    return resolve(getMeQuery.useQuery(), ({ data }) => ({ me: data.me }))
  })
  .plugin()

/**
 * Gate authorized-only points with this plugin — never check `me` by hand in a loader. Throws `UNAUTHORIZED` for
 * anonymous users; after it, `me` is non-null in ctx and props. For admin-only use `adminOnlyPlugin`.
 *
 * @tags rule, auth, plugin
 * @related adminOnlyPlugin, redirectUnauthorizedPlugin, mePlugin
 */
export const authorizedOnlyPlugin = Point0.lets
  .plugin()
  .use(mePlugin)
  .ctx(({ ctx: { me } }) => {
    if (!me) {
      throw new AppError('Only for authorized users', { code: 'UNAUTHORIZED' })
    }
    return { me }
  })
  .with(({ props: { me } }) => {
    if (!me) {
      return new AppError('Only for authorized users', { code: 'UNAUTHORIZED' })
    }
    return { me }
  })
  .plugin()

/**
 * Redirects to `home` when the user is already signed in. Use on sign-in / sign-up / password-reset pages so
 * authenticated users don't land there.
 *
 * @tags auth, plugin
 */
export const redirectAuthorizedPlugin = Point0.lets
  .plugin()
  .use(mePlugin)
  .ctx(({ ctx: { me } }) => {
    if (me) {
      return redirect('home')
    }
    // we do return here, to have type me === null
    return { me }
  })
  .with(({ props: { me } }) => {
    if (me) {
      return redirect('home')
    }
    return { me }
  })
  .plugin()

/**
 * Redirects to `signIn` for anonymous users. After this plugin, `me` is non-null in ctx and props.
 *
 * Prefer this over `authorizedOnlyPlugin` for pages where redirecting is friendlier than throwing.
 *
 * @tags auth, plugin
 */
export const redirectUnauthorizedPlugin = Point0.lets
  .plugin()
  .use(mePlugin)
  .ctx(({ ctx: { me } }) => {
    if (!me) {
      return redirect('signIn')
    }
    // we do return here, to have type me !== null
    return { me }
  })
  .with(({ props: { me } }) => {
    if (!me) {
      return redirect('signIn')
    }
    return { me }
  })
  .plugin()

/**
 * Throws `FORBIDDEN` for non-admin users. After this plugin, `me` is non-null and `me.admin === true`.
 *
 * Already applied by `adminBase`, so admin points get it for free.
 *
 * @tags auth, plugin, admin
 * @related adminBase
 */
export const adminOnlyPlugin = Point0.lets
  .plugin()
  .use(mePlugin)
  .ctx(({ ctx: { me } }) => {
    if (!me?.admin) {
      throw new AppError('Only for admins', { code: 'FORBIDDEN' })
    }
    return { me }
  })
  .with(({ props: { me } }) => {
    if (!me?.admin) {
      return new AppError('Only for admins', { code: 'FORBIDDEN' })
    }
    return { me }
  })
  .plugin()
