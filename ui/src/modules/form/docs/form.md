---
tags: form
related: fields
---

# Form

A thin layer over `react-hook-form` (RHF): a Zod `schema` that validates and
types the submit payload, a stable `form` handle, value subscriptions,
alerts/toasts, and layout. Everything it doesn't cover, you take from RHF
directly — `form.control`, `form.register`,
`useFormState({ control: form.control })`, `useController(...)`, etc.

## Declarative: `<FForm>`

The default. Pass `schema` + `onSubmit`, drop fields inside, done. Fields read
the form from context, so no `form` prop needed.

```tsx
import { FForm } from '@/modules/form/core/provider'
import { FFields, FFooter } from '@/modules/form/core/layout'
import { FButton } from '@/modules/form/core/button'
import { FInput } from '@/modules/form/fields/input'
import { z } from 'zod'
;<FForm
  schema={z.object({ email: z.email(), password: z.string().min(8) })}
  defaultValues={{ email: '', password: '' }}
  onSubmit={async (values) => api.signIn(values)}
  toastOnSuccess="Signed in"
>
  <FFields>
    <FInput name="email" label="Email" />
    <FInput name="password" label="Password" type="password" />
  </FFields>
  <FFooter>
    <FButton type="submit">Sign in</FButton>
  </FFooter>
</FForm>
```

`onSubmit(parsed, original, event)` gets the schema-parsed values first. A few
common props: `toastOn*` / `alertOn*` for feedback, `submitOnMount` /
`submitOnChange` for auto-submit, `clearFormOnSuccess`,
`buttonDisabledOnFormInvalid`, `buttonDisabledOnFormPristine`,
`fieldDisabledOnFormSubmitting`.

## Imperative: `useFForm`

Reach for this when you need the `form` handle outside the JSX — to trigger
submit from a button elsewhere, read values in logic, or reset on demand. Build
it with `useFForm(...)`, pass it to `<FForm form={form}>`, and call methods on
it.

```tsx
const form = useFForm({ schema, defaultValues, onSubmit })

form.submit() // validate + run onSubmit (same as a type="submit" button)
form.send(values) // validate + submit a value object you pass in
form.clear() // reset to defaultValues
;<FForm form={form}>{/* fields */}</FForm>
```

The handle is stable for the component's lifetime — safe in deps. It also
carries the usual RHF methods (`setValue`, `getValues`, `reset`, `setError`,
`control`, ...).

## Reading values

Three tools, pick by what you need.

**`form.useValues(...)`** — re-renders the component when the value changes.

```tsx
const all = form.useValues()
const email = form.useValues({ name: 'email', debounce: 300 })

// schema-parsed; falls back to last-known-valid
const { isValid, parsed } = form.useValues({ parsed: true })

// derive without re-rendering on every keystroke
const count = form.useValues({ name: 'items', compute: (xs) => xs.length })

// silent: callback fires, component does NOT re-render
form.useValues({ name: 'email' }, (email) => console.info(email))
```

**`<FValues>`** — same subscription, but inline in JSX. Takes `children` or
`render`; uses context or a `form` prop.

```tsx
<FValues name="email">{(email) => <span>{email}</span>}</FValues>
<FValues name="enabled" render={(on) => on && <FInput name="details" />} />
```

**`form.useSubscribe(...)`** — for side effects only. No re-render.

```tsx
form.useSubscribe({
  name: ['email', 'password'],
  formState: { values: true },
  callback: ({ values }) => console.info(values),
})
```

For **form state** (`isDirty`, `isValid`, `isSubmitting`, `errors`) don't use
any of the above — read it from RHF:

```tsx
const { isDirty, isSubmitting } = useFormState({ control: form.control })
```

## Alerts

`<FAlert />` renders the active success / validation-error / submit-error alert.
Turn it on with `alertOn*` props, drop `<FAlert />` above the button. Set one by
hand with `form.setAlert(...)`.

```tsx
<FForm schema={schema} onSubmit={onSubmit} alertOnSubmitError>
  <FFields>{/* fields */}</FFields>
  <FAlert />
  <FFooter>
    <FButton type="submit">Save</FButton>
  </FFooter>
</FForm>
```

## Buttons & layout

`FButton` has `type="submit" | "send" | "reset" | "clear"`. It subscribes only
to the form-state it needs and reads `buttonDisabledOnFormInvalid` / `Pristine`
from the form.

`FLayout` / `FFields` / `FSections` / `FFooter` are the layout pieces. `<FForm>`
is an `<FLayout as="form">` already, so inside it you only need `FFields` /
`FFooter`.

## Fields

Use the ready fields from `@/modules/form/fields/*` (`FInput`, `FSelect`,
`FSwitch`, `FRadioGroup`, ...). To build a new one, see
`@/modules/form/docs/fields.md`.

Under the hood every field is one of two wrappers:

- `FFieldUncontrolled` — wraps RHF `register()`. The default.
- `FFieldControlled` — wraps RHF `Controller`. Only when the control needs
  `value` / `onChange` directly.

Both add `label`, `description`, `errors`, `invalid`, `disabled`, `id`, `bare`.
For a true one-off you can use a wrapper inline instead of making a component:

```tsx
import { Input } from '@/components/ui/input'
import { FFieldUncontrolled } from '@/modules/form/core/field'
;<FFieldUncontrolled
  name="email"
  label="Email"
  render={({ id, invalid, disabled, initialValue, register }) => (
    <Input
      {...register()}
      defaultValue={initialValue}
      id={id}
      aria-invalid={invalid}
      disabled={disabled}
    />
  )}
/>
```

> `disabled` on the wrappers is UI-only. Don't pass it into the RHF controller —
> RHF drops disabled values from the submit payload.

## Outside the context

If a component can't reach the `<FForm>` context, import `useFValues` from
`@/modules/form/core/values` and pass `{ form }` explicitly.
