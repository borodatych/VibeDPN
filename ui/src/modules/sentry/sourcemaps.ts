#!/usr/bin/env bun
/* eslint-disable no-console -- standalone build script, runs outside the app runtime */

/**
 * Upload sourcemaps to Sentry after `point0 build`. Bundler-agnostic — works whether the client was built by Bun or by
 * Vite, because Point0 emits external `.map` files for both. `sourcemaps inject` stamps Debug IDs into the bundles, so
 * Sentry resolves minified stack traces even if the runtime release differs from the uploaded one. Inject + upload only
 * — it never deletes the maps, so the Dockerfile's `.map` cleanup step can run after it in any order.
 *
 * Self-skips when `SENTRY_AUTH_TOKEN` is unset, so `bun run build` stays green on a laptop. Set the token (plus
 * `SENTRY_ORG`, `SENTRY_PROJECT_SERVER`, `SENTRY_PROJECT_CLIENT`) in CI to enable uploads. Stripping the now-uploaded
 * client `.map`s from the served `dist/client` is a final step in the Dockerfile.
 *
 * @tags sentry, setup, script
 * @related sentry
 */

import { $ } from 'bun'
import { z } from 'zod'

// eslint-disable-next-line no-restricted-properties -- build-time CI secret, deliberately not in any app env shape
if (!process.env.SENTRY_AUTH_TOKEN) {
  console.log('[sentry] SENTRY_AUTH_TOKEN not set — skipping sourcemap upload')
  process.exit(0)
}

const parsed = z
  .object({
    SENTRY_ORG: z.string().min(1),
    SENTRY_PROJECT_SERVER: z.string().min(1),
    SENTRY_PROJECT_CLIENT: z.string().min(1),
    SOURCE_VERSION: z.string().min(1).optional(),
  })
  // eslint-disable-next-line no-restricted-properties -- build script: these SENTRY_* vars exist only in CI, not in the app env
  .safeParse(process.env)

if (!parsed.success) {
  console.error(`[sentry] invalid environment for sourcemap upload:\n${z.prettifyError(parsed.error)}`)
  process.exit(1)
}

const { SENTRY_ORG, SENTRY_PROJECT_SERVER, SENTRY_PROJECT_CLIENT, SOURCE_VERSION } = parsed.data

// Use the project-local CLI (3.x) — a globally installed `sentry-cli` may be older and would win on PATH otherwise.
// `$` inherits process.env, so the auth token reaches the CLI without passing it explicitly.
const cli = `${process.cwd()}/node_modules/.bin/sentry-cli`
const sentry = async (args: string[]) => await $`${cli} ${args}`

const gitSha = await $`git rev-parse --short HEAD`.nothrow().quiet()
const release = SOURCE_VERSION ?? (gitSha.exitCode === 0 ? gitSha.text().trim() : undefined)

const targets = [
  { project: SENTRY_PROJECT_SERVER, dir: 'dist/server' },
  { project: SENTRY_PROJECT_CLIENT, dir: 'dist/client' },
]

console.log(`[sentry] uploading sourcemaps${release ? ` for release ${release}` : ''}`)
for (const { project, dir } of targets) {
  const releaseArgs = release ? ['--release', release] : []
  await sentry(['sourcemaps', 'inject', dir])
  await sentry(['sourcemaps', 'upload', '--org', SENTRY_ORG, '--project', project, ...releaseArgs, dir])
  if (release) {
    await sentry(['releases', '--org', SENTRY_ORG, '--project', project, 'new', release])
    await sentry(['releases', '--org', SENTRY_ORG, '--project', project, 'finalize', release])
  }
}
console.log('[sentry] sourcemaps uploaded')
