---
tags: form, fields
related: form
---

# Creating form fields

Fields here adapt a UI component from `@/components/ui/*` to the form core. One
field component per control.

Two flavors:

- **Uncontrolled** (`FFieldUncontrolled`) — the default. Spreads RHF
  `register()` onto a native input, so it doesn't re-render on every keystroke.
- **Controlled** (`FFieldControlled`) — only when the control needs `value` /
  `onChange` directly: masked inputs, custom selects, switches, anything without
  a native uncontrolled input.

Make only the flavor your control actually needs.
`@/modules/form/fields/input.tsx` keeps both (`FInput` and `FInputControlled`)
as a side-by-side example. The ready-made fields live in
`@/modules/form/fields`.

## Recipe

1. Start from a UI component in `@/components/ui`. If the field combines several
   pieces, first build an `X*` component at the **bottom** of that UI file
   (after the original exports, as `export function` / `export const` — don't
   touch the generated export block), then adapt it here.
2. Type the props with
   `WithFFieldUncontrolledProps<React.ComponentProps<typeof XComponent>, ...>`
   (or the `Controlled` version).
3. Split them with `splitFFieldUncontrolledProps(props)` (or
   `splitFFieldControlledProps`).
4. Render through `FFieldUncontrolled` / `FFieldControlled`; pass the rest to
   the UI component.
5. Wire the field state from the render callback: `id`,
   `aria-invalid={invalid}`, `disabled={disabled}`.

Uncontrolled: spread `register()` and set `defaultValue={initialValue}`.
Controlled: spread `field`, forward `field.ref`, and normalize empties where
needed (`value={field.value ?? ''}`).

## Uncontrolled example (`FInput`)

```tsx
export function FInput(props) {
  const { uncontrolledProps, rest } = splitFFieldUncontrolledProps(props)
  return (
    <FFieldUncontrolled
      {...uncontrolledProps}
      render={({ id, invalid, disabled, initialValue, register }) => (
        <XInput
          {...rest}
          {...register()}
          defaultValue={initialValue}
          id={id}
          aria-invalid={invalid}
          disabled={disabled}
        />
      )}
    />
  )
}
```

## Controlled example (`FSelect`)

```tsx
export function FSelect(props) {
  const { controlledProps, rest } = splitFFieldControlledProps(props)
  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => (
        <XSelect
          {...rest}
          value={field.value}
          onValueChange={field.onChange}
          disabled={disabled}
          triggerProps={{
            id,
            ref: field.ref,
            'aria-invalid': invalid,
            onBlur: field.onBlur,
          }}
        />
      )}
    />
  )
}
```

See `@/modules/form/fields/input.tsx`, `@/modules/form/fields/select.tsx`,
`@/modules/form/fields/switch.tsx` for the full versions.
