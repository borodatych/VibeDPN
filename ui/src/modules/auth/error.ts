import { Error0 } from '@1gr14/error0'
import type { BetterFetchError } from 'better-auth/react'

const betterAuthErrorsMap = {
  invalid_callback_request: 'The callback request is invalid',
  invalid_code: 'The provided authentication code is invalid or expired',
  internal_server_error: 'An unexpected error occurred during authentication',
  state_not_found: 'The state parameter was not found in the request',
  state_mismatch: 'State verification failed during the OAuth callback',
  no_code: 'The code was not found in the request',
  no_callback_url: 'The callback URL was not found in the request',
  oauth_provider_not_found: 'The OAuth provider was not found',
  email_not_found: 'The provider did not return an email address',
  "email_doesn't_match": "The email doesn't match the email of the account.",
  unable_to_get_user_info: 'The user info was not found in the request',
  unable_to_link_account: 'The account could not be linked',
  unable_to_create_user: 'The user could not be created during authentication',
  unable_to_create_session: 'The session could not be created during authentication',
  account_not_linked: 'The provider account is not linked to the current user and cannot be linked automatically',
  account_already_linked_to_different_user: 'The account is already linked to a different user',
  signup_disabled: 'Signup disabled error',
  please_restart_the_process: 'The OAuth state could not be parsed. The sign-in flow must be restarted',
}

export const toBetterAuthMessageIfSuitable = (message: string) => {
  return (message && betterAuthErrorsMap[message as keyof typeof betterAuthErrorsMap]) || message
}

export const betterAuthErrorPlugin = Error0.plugin()
  // The client-side better-auth error: `authClient` calls reject with a `BetterFetchError`.
  .prop('betterAuthFetchError', {
    init: (betterAuthFetchError: BetterFetchError) => betterAuthFetchError,
  })
  .adapt((error) => {
    const cause = error.cause
    // Match by string, not `instanceof` — a value import would pull better-call into the client bundle. better-call's
    // APIError overrides `.constructor` to base Error, so match it by `.name` + its shape; BetterFetchError by ctor name.
    if (cause instanceof Error && cause.constructor.name === 'BetterFetchError') {
      const hiddenError = 'error' in cause ? cause.error : undefined
      const hiddenErrorMessage =
        typeof hiddenError === 'object' &&
        hiddenError !== null &&
        'message' in hiddenError &&
        typeof hiddenError.message === 'string' &&
        hiddenError.message
      if (hiddenErrorMessage) {
        error.message = hiddenErrorMessage
      }
      ;(error as { expected?: boolean }).expected = true
      error.betterAuthFetchError = cause as BetterFetchError
    }
    if (
      cause instanceof Error &&
      cause.name === 'APIError' &&
      'statusCode' in cause &&
      typeof cause.statusCode === 'number' &&
      'status' in cause &&
      'body' in cause
    ) {
      // Pass the APIError's real status + message through, so the request answers 401 (the CLI re-logins off it), not 500.
      error.message = cause.message
      ;(error as { status?: number }).status = cause.statusCode
      ;(error as { expected?: boolean }).expected = true
    }
  })
