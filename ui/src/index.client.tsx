import '@/styles/index.css'

import App from '@/app.client'
import { ErrorBoundary } from '@/components/other/error-boundary'
import { clientEnv } from '@/modules/env/client'
import { initMixpanelClient } from '@/modules/mixpanel/client'
import { initSentryClient } from '@/modules/sentry/client'
import points from '@/generated/point0/points.client'
import { mount } from '@point0/react-dom/mount'

// Browser entry — never imported during SSR, so this all runs only in the browser. Validate the client env first (a
// missing/invalid public var fails loudly here, not lazily mid-render), then init telemetry — all before mounting, so
// the first paint is already covered by Sentry/Mixpanel.
clientEnv.validate()
initSentryClient()
initMixpanelClient()

mount(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
  points,
)

// eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
if (import.meta.hot) {
  import.meta.hot.accept()
}
