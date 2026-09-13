import { FButton } from '@/modules/form/core/button'
import { FFields, FFooter } from '@/modules/form/core/layout'
import { FForm } from '@/modules/form/core/provider'
import { FInput } from '@/modules/form/fields/input'
import { getMeQuery } from '@/modules/auth/api'
import { authClient } from '@/modules/auth/client'
import { z } from 'zod'

// Mirrors BOX_ADMIN_EMAIL on the server: the box has one account, so the form asks only for the password.
const BOX_ADMIN_EMAIL = 'admin@vibedpn.lan'

export const SignInForm = ({ onSuccess }: { onSuccess?: () => void }) => {
  return (
    <FForm
      id="sign-in-form"
      schema={z.object({
        password: z.string().min(1),
      })}
      onSubmit={async ({ password }) => {
        await authClient.signIn.email({ email: BOX_ADMIN_EMAIL, password })
        return await getMeQuery.refetchQuery()
      }}
      onSuccess={() => {
        onSuccess?.()
      }}
      defaultValues={{ password: '' }}
      size="sm"
    >
      <FFields>
        <FInput
          name="password"
          label="Password"
          placeholder="The password from vibedpn init"
          inputSize="xl"
          type="password"
          autoComplete="current-password"
        />
      </FFields>
      <FFooter>
        <FButton type="submit" size="2xl">
          Sign In
        </FButton>
      </FFooter>
    </FForm>
  )
}
