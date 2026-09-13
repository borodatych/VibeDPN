// Resolve SOURCE_VERSION from the platform's git SHA before anything reads it. Railway injects the deploy's commit as
// RAILWAY_GIT_COMMIT_SHA into the runtime container env (confirmed live), but NOT into the `${{...}}` variable graph — so
// a `SOURCE_VERSION=${{RAILWAY_GIT_COMMIT_SHA}}` reference resolves to an empty string. Read it straight from the env.
// An explicit SOURCE_VERSION still wins; the guard avoids assigning `undefined` (process.env would coerce it to the
// string "undefined"). Must run before preload and before telemetry reads the release.
// eslint-disable-next-line no-restricted-properties -- boot entry, runs before preload loads env; this IS the fix-up
if (!process.env.SOURCE_VERSION && process.env.RAILWAY_GIT_COMMIT_SHA) {
  // eslint-disable-next-line no-restricted-properties -- RAILWAY_GIT_COMMIT_SHA is platform-injected, in no shape
  process.env.SOURCE_VERSION = process.env.RAILWAY_GIT_COMMIT_SHA
}

// Server entry. The preload must finish first: it registers the Point0 compiler plugins (and env
// consts), so everything app.server.ts imports goes through them. Any direct `bun src/<file>.ts`
// run that imports app code needs the same `await import('@/preload')` first line.
await import('./preload')

// Validate the whole server env right after preload loads it, so a missing/invalid variable fails the boot loudly, not
// lazily mid-request. Dynamic import on purpose: `serverEnv`'s shape reads NODE_ENV/HOST_ENV when its module evaluates,
// which must happen after preload. This is the server entry (never bundled to the client).
const { serverEnv } = await import('./modules/env/server')
serverEnv.validate()

// Init telemetry before booting, so startup failures are captured and server-side events are tracked. Dynamic import
// (like above) so it happens after preload — these modules read the server env when they evaluate.
const { initSentryServer } = await import('./modules/sentry/server')
const { initMixpanelServer } = await import('./modules/mixpanel/server')
const { initAxiom } = await import('./modules/axiom')
await initSentryServer()
initMixpanelServer()
await initAxiom()

await import('./app.server')

// Server HMR — Vite only. Uncomment together with `viteConfig` in engine.ts when switching the bundler to
// Vite. It must sit on this entry (not app.server.ts): a page edit then re-serves granularly instead of a
// full reload that skips dispose and leaves the port bound. Bun is fine without it.
// // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
// if (import.meta.hot) {
//   const { engine } = await import('./engine')
//   import.meta.hot.dispose(async () => await engine.dispose())
//   import.meta.hot.accept()
// }

// Only dynamic imports above (the order matters); this marks the file as a module for TypeScript.
export {}
