import { createQueryClient } from '@point0/core'

// Point0 constructs the QueryClient itself so its defaults merge with yours; pass a `() => QueryClientConfig` to
// customize (we keep the defaults), never a QueryClient instance.
export const queryClient = createQueryClient()
