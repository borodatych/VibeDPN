import { appChannel } from '@/modules/socket/channel'
import { AuthSocketSync } from '@/modules/auth/socket'
import { Router, RouterRoutes } from '@/lib/navigation'
import { UnheadProvider } from '@point0/core/unhead'
import { QueryClientProvider } from '@tanstack/react-query'
// import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { NProgress } from '@/components/other/nprogress'
import { SearchParamsToast, Toaster } from '@/components/ui/sonner'
import { ThemeProvider } from '@/components/ui/theme'
import { ErrorPageComponent } from '@/components/other/error'
import { queryClient } from '@/lib/query-client'
import { AuthDrawer } from '@/modules/auth/components/drawer'
import { MixpanelTrackAuth } from '@/modules/mixpanel/track-auth'
import { MixpanelTrackPage } from '@/modules/mixpanel/track-page'
import { SentryTrackAuth } from '@/modules/sentry/track-auth'
import { Head } from '@unhead/react'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* <ReactQueryDevtools initialIsOpen={true} /> */}
      <UnheadProvider>
        <Head>
          <link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
          <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
          <link rel="shortcut icon" href="/favicon.ico" />
          <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
          <meta name="apple-mobile-web-app-title" content="VibeDPN" />
          <link rel="manifest" href="/site.webmanifest" />
        </Head>
        <ThemeProvider />
        <Router>
          <NProgress />
          <Toaster />
          <SearchParamsToast />
          <SentryTrackAuth />
          <MixpanelTrackAuth />
          <MixpanelTrackPage />
          <AuthDrawer />
          {/* gate={false}: the app renders through connecting and even a failed connect — the socket is an enhancement here */}
          <appChannel.Connection gate={false}>
            <AuthSocketSync />
            <RouterRoutes Page404={() => <ErrorPageComponent title="404" description="Page not found" />} />
          </appChannel.Connection>
        </Router>
      </UnheadProvider>
    </QueryClientProvider>
  )
}
