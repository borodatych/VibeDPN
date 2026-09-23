import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import {
  MAX_ALERT_AFTER_SECONDS,
  MAX_TOKEN_CHARS,
  MIN_ALERT_AFTER_SECONDS,
  WEEKDAYS,
  type TelegramBot,
} from '@/features/telegram/shared'
import { z } from 'zod'

// While a link waits to be opened, the page sees the chat linked within seconds.
const REFRESH_MS = 3_000
// 404: this core runs no bot — the page explains instead of failing.
const NOT_HERE = 404
// Core calls Telegram itself for these: the token and the test go through the exit of the box, Tor included
// (core/vibedpn/api/client.py TELEGRAM_WAIT_SECONDS).
const TELEGRAM_WAIT_MS = 35_000
const LAST_HOUR = 23
const MAX_TIMEZONE_CHARS = 64

export const telegramQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<TelegramBot>('/telegram')
    if (answer.ok) {
      return { bot: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { bot: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const telegramSettingsMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // a field left null stays as it is in config.yaml
  .input(
    z.object({
      enabled: z.boolean().nullable(),
      alert_after_seconds: z.number().int().min(MIN_ALERT_AFTER_SECONDS).max(MAX_ALERT_AFTER_SECONDS).nullable(),
      timezone: z.string().max(MAX_TIMEZONE_CHARS).nullable(),
      report_enabled: z.boolean().nullable(),
      report_weekday: z.enum(WEEKDAYS).nullable(),
      report_hour: z.number().int().min(0).max(LAST_HOUR).nullable(),
    }),
  )
  .loader(async ({ input }) => {
    return { bot: await coreRequest<TelegramBot>('/telegram', { method: 'PUT', body: input }) }
  })
  .mutation()

// The token goes to core, which checks it with Telegram and keeps it; it never comes back.
export const telegramTokenMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ token: z.string().max(MAX_TOKEN_CHARS) }))
  .loader(async ({ input }) => {
    return {
      bot: await coreRequest<TelegramBot>('/telegram/token', { method: 'POST', body: input }, TELEGRAM_WAIT_MS),
    }
  })
  .mutation()

export const telegramLinkMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { bot: await coreRequest<TelegramBot>('/telegram/link', { method: 'POST', body: {} }) }
  })
  .mutation()

export const telegramTestMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    await coreRequest<null>('/telegram/test', { method: 'POST', body: {} }, TELEGRAM_WAIT_MS)
    return { sent: true }
  })
  .mutation()
