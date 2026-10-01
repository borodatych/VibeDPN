import { AppError } from '@/lib/error'
import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { authServer } from '@/modules/auth/server'
import { coreFetch } from '@/modules/core/client'
import type { PanelPasswordView } from '@/features/password/shared'
import { z } from 'zod'

// core refuses a current password that is not the one of secrets/htpasswd
const WRONG_CURRENT = 403

export const panelPasswordMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ current: z.string().min(1), new: z.string().min(1) }))
  .loader(async ({ input, request }) => {
    const answer = await coreFetch<PanelPasswordView>('/panel/password', { method: 'PUT', body: input })
    if (!answer.ok) {
      if (answer.status === WRONG_CURRENT) {
        return { password: null, wrongCurrent: true }
      }
      throw new AppError(answer.detail, { status: answer.status })
    }
    // A password changed because it leaked must end the sign-ins made with it: only this one stays
    await authServer.api.revokeOtherSessions({ headers: request.original.headers })
    return { password: answer.body, wrongCurrent: false }
  })
  .mutation()
