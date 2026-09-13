import { engine } from './engine'

await engine.preload({ nodeEnvFallback: 'development', preventLoadBunPlugins: !!engine.server.viteConfig })
