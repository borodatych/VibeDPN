import { Engine } from '@point0/engine'
// Uncomment these together with `viteConfig` below to switch the bundler to Vite.
// import tailwindcss from '@tailwindcss/vite'
// import react from '@vitejs/plugin-react'
// import svgr from 'vite-plugin-svgr'
// import { analyzer } from 'vite-bundle-analyzer'
import { clientEnvKeys } from './modules/env/shared'

// The panel variant (docs/uiVariants.md), baked into both bundles as a build-time constant.
// Rule for code that exists only in `full` (workers, history charts, node statistics, live subscriptions): branch on
// `process.env.UI_VARIANT` right where the code is used. The compiler inlines only that expression; a boolean exported
// from another module is a variable to the bundler, and the branch with its imports would ship in `lite` too.
// eslint-disable-next-line no-restricted-properties -- config load also happens for builds and codegen, with no env
const uiVariant = process.env.UI_VARIANT === 'lite' ? 'lite' : 'full'
export const engine = Engine.create({
  file: import.meta.url,
  ssr: true,
  pointsGlob: '**/*.{ts,tsx,mdx}',
  generate: { meta: './generated/point0/meta.ts', assetsTypes: './generated/point0/assets.d.ts' },
  logger: async () => {
    const { logger } = await import('@/lib/logger')
    return {
      log: ({ category, level, message, error, meta }) => {
        logger.log({ level, category, input: message, props: { ...meta, ...(error ? { error } : {}) } })
      },
    }
  },
  server: {
    scope: 'root',
    // The ports are the one env this file may read raw. `Engine.create` runs at config-load time, which is also every
    // `point0 build` and `point0 generate` — and those run with no env file at all (the Docker build stage ships none),
    // so a validated `serverEnv.SERVER_PORT` would throw on a variable the build never needs. Everything else the
    // engine wants from env is behind a lazy factory below.
    // eslint-disable-next-line no-restricted-properties -- config load also happens for builds and codegen, with no env
    port: process.env.SERVER_PORT || process.env.PORT,
    // The panel listens on the LAN address only (Bun's default is 0.0.0.0); serverEnv requires it in production.
    // eslint-disable-next-line no-restricted-properties -- config load also happens for builds and codegen, with no env
    bunServeConfig: { hostname: process.env.UI_LISTEN_HOST },
    // the bare WebSocket endpoint the app channel multiplexes over
    socket: true,
    // cross-process delivery over the Postgres the app already runs (see lib/backplane). The engine calls this factory
    // on server start only, so the module — its postgres client and its env read — never loads at config load, which
    // also happens for a build and for codegen. `lite` runs one process: sockets stay in its memory, no pool, no LISTEN.
    ...(uiVariant === 'full' ? { backplane: async () => (await import('@/lib/backplane')).backplane } : {}),
    env: { consts: { UI_VARIANT: uiVariant } },
    entry: { main: './index.server.ts' },
    points: async () => await import('./generated/point0/points.server'),
    generate: { points: './generated/point0/points.server.ts' },
    outdir: '../dist/server',
  },
  // To use Vite as the bundler: uncomment the vite imports above + this `viteConfig` + the server-HMR block
  // in index.server.ts, and apply the marked fixes in index.client.html.
  // viteConfig: ({ plugins, side }) => {
  //   const external = ['bun', '@tailwindcss/vite', '@tailwindcss/oxide', '@tailwindcss/node', 'tailwindcss']
  //   return {
  //     plugins: [
  //       ...plugins,
  //       react({ include: /\.(jsx|js|mdx|md|tsx|ts)$/ }),
  //       svgr(),
  //       tailwindcss(),
  //       side === 'client' ? analyzer() : null,
  //     ],
  //     resolve: {
  //       tsconfigPaths: true,
  //     },
  //     optimizeDeps: {
  //       exclude: external,
  //     },
  //     ssr: {
  //       external,
  //     },
  //   }
  // },
  client: {
    scope: 'root',
    // eslint-disable-next-line no-restricted-properties -- config load also happens for builds and codegen, with no env
    port: process.env.CLIENT_PORT,
    indexHtml: './index.client.html',
    app: async () => await import('./app.client'),
    points: async () => await import('./generated/point0/points.client'),
    generate: {
      points: './generated/point0/points.client.ts',
      routes: { outfile: './generated/point0/routes.ts', origin: 'process.env.CLIENT_URL' },
    },
    bunPlugins: ['bun-plugin-tailwind'],
    env: { vars: clientEnvKeys, consts: { UI_VARIANT: uiVariant } },
    outdir: '../dist/client',
    publicdir: {
      source: [
        '../public',
        {
          '.well-known/appspecific/com.chrome.devtools.json': () => '{}',
        },
      ],
      outdir: '../dist/client',
    },
  },
})
