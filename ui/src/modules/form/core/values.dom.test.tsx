/* eslint-disable react-hooks/rules-of-hooks -- type-only assertions call hooks outside components */
/**
 * Comprehensive tests for `useFValues`, `form.useValues`, and `<FValues />`.
 *
 * Layout:
 *
 * 1. Type-level overload assertions (compile-time only; never invoked).
 * 2. Runtime tests for `form.useValues` — raw / parsed / callbacks / behavior.
 * 3. Runtime tests for `<FValues />` — render & children, every selector, parsed mode, and context fallback.
 *
 * The type-level section calls `expectTypeOf(...)` inside dead-code functions so that `bun types` (tsgo) verifies every
 * overload combination of `useFValues` and `<FValues />` produces the documented value / render-arg shape, while
 * runtime stays a no-op.
 */
import { describe, expect, expectTypeOf, mock, test } from 'bun:test'
import { act, render, screen } from '@testing-library/react'
import { type ReactNode } from 'react'
import { type DeepPartialSkipArrayKey } from 'react-hook-form'
import { z } from 'zod'

import { useFForm, type UseFFormReturn } from './hook'
import { FForm } from './provider'
import {
  FValues,
  useFValues,
  type UseFValuesValidComputedResult,
  type UseFValuesValidPickResult,
  type UseFValuesValidResult,
  type UseFValuesValidTupleResult,
} from './values'

// =============================================================================
// SECTION 1 — Type-level overload assertions (compile-time only).
//
// The two functions below are never invoked at runtime. They exist purely so
// that the TypeScript compiler (via `bun types`) verifies the return /
// render-arg type for every overload of `useFValues`, `form.useValues`,
// and `<FValues />`. If an overload regresses, `bun types` fails.
// =============================================================================

type FV = { name: string; age: number; tag?: string }
// Raw vs. parsed split — emulates a schema that coerces strings to numbers.
type FVRaw = { count: string; toggle: string }
type FVParsed = { count: number; toggle: boolean }

function _useFValuesTypeChecks() {
  const form = null as unknown as UseFFormReturn<FV, FV>
  const formP = null as unknown as UseFFormReturn<FVRaw, FVParsed>

  // ---------------------------------------------------------------------------
  // RAW mode (parsed: false | undefined)
  // ---------------------------------------------------------------------------

  // No selector
  expectTypeOf(form.useValues()).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
  expectTypeOf(form.useValues({})).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
  expectTypeOf(form.useValues({ disabled: true })).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
  expectTypeOf(form.useValues({ defaultValues: { name: 'a', age: 1 } })).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
  expectTypeOf(form.useValues({ compute: (v) => v.name.length })).toEqualTypeOf<number>()

  // Name (string)
  expectTypeOf(form.useValues({ name: 'name' })).toEqualTypeOf<string>()
  expectTypeOf(form.useValues({ name: 'age' })).toEqualTypeOf<number>()
  expectTypeOf(form.useValues({ name: 'name', defaultValues: 'a' })).toEqualTypeOf<string>()
  expectTypeOf(form.useValues({ name: 'name', compute: (v) => v.toUpperCase() })).toEqualTypeOf<string>()
  expectTypeOf(form.useValues({ name: 'age', compute: (v) => `${v}` })).toEqualTypeOf<string>()

  // Name (tuple)
  expectTypeOf(form.useValues({ name: ['name', 'age'] as const })).toEqualTypeOf<[string, number]>()
  expectTypeOf(
    form.useValues({ name: ['name', 'age'] as const, compute: ([n, a]) => `${n}/${a}` }),
  ).toEqualTypeOf<string>()

  // Pick selector
  expectTypeOf(form.useValues({ pick: ['name'] as const })).toEqualTypeOf<Pick<FV, 'name'>>()
  expectTypeOf(form.useValues({ pick: ['name', 'age'] as const })).toEqualTypeOf<Pick<FV, 'name' | 'age'>>()
  expectTypeOf(form.useValues({ pick: ['name'] as const, compute: (v) => v.name })).toEqualTypeOf<string>()

  // Omit selector
  expectTypeOf(form.useValues({ omit: ['name'] as const })).toEqualTypeOf<Omit<FV, 'name'>>()
  expectTypeOf(form.useValues({ omit: ['name'] as const, compute: (v) => v.age })).toEqualTypeOf<number>()

  // ---------------------------------------------------------------------------
  // PARSED mode (parsed: true)
  // ---------------------------------------------------------------------------

  // No selector
  expectTypeOf(formP.useValues({ parsed: true, defaultValues: { count: 0, toggle: false } })).toEqualTypeOf<FVParsed>()
  expectTypeOf(formP.useValues({ parsed: true })).toEqualTypeOf<
    UseFValuesValidResult<DeepPartialSkipArrayKey<FVRaw>, FVParsed>
  >()
  expectTypeOf(
    formP.useValues({ parsed: true, defaultValues: { count: 0, toggle: false }, compute: (v) => v.count + 1 }),
  ).toEqualTypeOf<number>()
  expectTypeOf(formP.useValues({ parsed: true, compute: (v) => v.count + 1 })).toEqualTypeOf<
    UseFValuesValidComputedResult<number>
  >()

  // Name (string)
  expectTypeOf(formP.useValues({ parsed: true, name: 'count', defaultValues: 0 })).toEqualTypeOf<number>()
  expectTypeOf(formP.useValues({ parsed: true, name: 'count' })).toEqualTypeOf<UseFValuesValidResult<string, number>>()
  expectTypeOf(
    formP.useValues({ parsed: true, name: 'count', defaultValues: 0, compute: (v) => v * 2 }),
  ).toEqualTypeOf<number>()
  expectTypeOf(formP.useValues({ parsed: true, name: 'count', compute: (v) => v * 2 })).toEqualTypeOf<
    UseFValuesValidComputedResult<number>
  >()

  // Name (tuple)
  expectTypeOf(
    formP.useValues({
      parsed: true,
      name: ['count', 'toggle'] as const,
      defaultValues: [0, false] as [number, boolean],
    }),
  ).toEqualTypeOf<[number, boolean]>()
  expectTypeOf(formP.useValues({ parsed: true, name: ['count', 'toggle'] as const })).toEqualTypeOf<
    UseFValuesValidTupleResult<[number, boolean], [string, string]>
  >()
  expectTypeOf(
    formP.useValues({
      parsed: true,
      name: ['count', 'toggle'] as const,
      defaultValues: [0, false] as [number, boolean],
      compute: ([n, b]) => `${n}/${b}`,
    }),
  ).toEqualTypeOf<string>()
  expectTypeOf(
    formP.useValues({
      parsed: true,
      name: ['count', 'toggle'] as const,
      compute: ([n, b]) => `${n}/${b}`,
    }),
  ).toEqualTypeOf<UseFValuesValidComputedResult<string>>()

  // Pick
  expectTypeOf(formP.useValues({ parsed: true, pick: ['count'] as const, defaultValues: { count: 0 } })).toEqualTypeOf<
    Pick<FVParsed, 'count'>
  >()
  expectTypeOf(formP.useValues({ parsed: true, pick: ['count'] as const })).toEqualTypeOf<
    UseFValuesValidPickResult<FVParsed, readonly ['count'], Pick<FVRaw, 'count'>>
  >()
  expectTypeOf(
    formP.useValues({
      parsed: true,
      pick: ['count'] as const,
      defaultValues: { count: 0 },
      compute: (v) => v.count,
    }),
  ).toEqualTypeOf<number>()
  expectTypeOf(formP.useValues({ parsed: true, pick: ['count'] as const, compute: (v) => v.count })).toEqualTypeOf<
    UseFValuesValidComputedResult<number>
  >()

  // Omit
  expectTypeOf(
    formP.useValues({ parsed: true, omit: ['count'] as const, defaultValues: { toggle: false } }),
  ).toEqualTypeOf<Omit<FVParsed, 'count'>>()
  expectTypeOf(formP.useValues({ parsed: true, omit: ['count'] as const })).toEqualTypeOf<
    UseFValuesValidResult<Omit<FVRaw, 'count'>, Omit<FVParsed, 'count'>>
  >()
  expectTypeOf(
    formP.useValues({
      parsed: true,
      omit: ['count'] as const,
      defaultValues: { toggle: false },
      compute: (v) => v.toggle,
    }),
  ).toEqualTypeOf<boolean>()
  expectTypeOf(formP.useValues({ parsed: true, omit: ['count'] as const, compute: (v) => v.toggle })).toEqualTypeOf<
    UseFValuesValidComputedResult<boolean>
  >()

  // ---------------------------------------------------------------------------
  // Callback variants — every overload's silent-subscription counterpart.
  // ---------------------------------------------------------------------------

  // Shorthand
  expectTypeOf(
    form.useValues((v) => {
      expectTypeOf(v).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
    }),
  ).toEqualTypeOf<undefined>()

  // Raw, no selector
  expectTypeOf(
    form.useValues({}, (v) => {
      expectTypeOf(v).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
    }),
  ).toEqualTypeOf<undefined>()
  expectTypeOf(
    form.useValues({ compute: (v) => v.name }, (v) => {
      expectTypeOf(v).toEqualTypeOf<string>()
    }),
  ).toEqualTypeOf<undefined>()

  // Raw, name
  expectTypeOf(
    form.useValues({ name: 'name' }, (v) => {
      expectTypeOf(v).toEqualTypeOf<string>()
    }),
  ).toEqualTypeOf<undefined>()
  expectTypeOf(
    form.useValues({ name: 'name', compute: (s) => s.length }, (v) => {
      expectTypeOf(v).toEqualTypeOf<number>()
    }),
  ).toEqualTypeOf<undefined>()

  // Raw, tuple
  expectTypeOf(
    form.useValues({ name: ['name', 'age'] as const }, (v) => {
      expectTypeOf(v).toEqualTypeOf<[string, number]>()
    }),
  ).toEqualTypeOf<undefined>()

  // Raw, pick / omit
  expectTypeOf(
    form.useValues({ pick: ['name'] as const }, (v) => {
      expectTypeOf(v).toEqualTypeOf<Pick<FV, 'name'>>()
    }),
  ).toEqualTypeOf<undefined>()
  expectTypeOf(
    form.useValues({ omit: ['name'] as const }, (v) => {
      expectTypeOf(v).toEqualTypeOf<Omit<FV, 'name'>>()
    }),
  ).toEqualTypeOf<undefined>()

  // Parsed, name
  expectTypeOf(
    formP.useValues({ parsed: true, name: 'count' }, (v) => {
      expectTypeOf(v).toEqualTypeOf<UseFValuesValidResult<string, number>>()
    }),
  ).toEqualTypeOf<undefined>()
  expectTypeOf(
    formP.useValues({ parsed: true, name: 'count', defaultValues: 0 }, (v) => {
      expectTypeOf(v).toEqualTypeOf<number>()
    }),
  ).toEqualTypeOf<undefined>()

  // ---------------------------------------------------------------------------
  // Standalone hook (`useFValues(...)`).
  //
  // `useFValues` defaults its outer generics to `FieldValues`, but each
  // overload promotes them into **per-call** generics that infer from the
  // optional `form?` prop (powered by `NoInfer<>` on `defaultValues`/`compute`,
  // so only `form` drives inference). With a typed `form`, the result is just
  // as tight as `form.useValues(...)`. Without `form`, it degrades to a
  // permissive any-ish shape.
  // ---------------------------------------------------------------------------

  // No `form` prop → FieldPath<FieldValues> degrades to `string`,
  // FieldPathValue<FieldValues, any> degrades to `any`.
  const anyValue = useFValues({ name: 'arbitrary' })
  expectTypeOf(anyValue).toBeAny()
  const anyComputed = useFValues({ name: 'arbitrary', compute: (v) => v })
  expectTypeOf(anyComputed).toBeAny()
  expectTypeOf(useFValues()).toEqualTypeOf<DeepPartialSkipArrayKey<Record<string, any>>>()

  // With a typed `form` prop, the standalone hook infers `TFieldValues` from
  // the form just like `<FValues form={form} ... />`.
  expectTypeOf(useFValues({ form })).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
  expectTypeOf(useFValues({ form, name: 'name' })).toEqualTypeOf<string>()
  expectTypeOf(useFValues({ form, name: 'age' })).toEqualTypeOf<number>()
  expectTypeOf(useFValues({ form, name: 'name', defaultValues: 'a' })).toEqualTypeOf<string>()
  expectTypeOf(useFValues({ form, name: 'name', compute: (v) => v.toUpperCase() })).toEqualTypeOf<string>()
  expectTypeOf(useFValues({ form, name: ['name', 'age'] as const })).toEqualTypeOf<[string, number]>()
  expectTypeOf(useFValues({ form, pick: ['name'] as const })).toEqualTypeOf<Pick<FV, 'name'>>()
  expectTypeOf(useFValues({ form, omit: ['tag'] as const })).toEqualTypeOf<Omit<FV, 'tag'>>()
  expectTypeOf(useFValues({ form, compute: (v) => v.name.length })).toEqualTypeOf<number>()

  // Parsed mode with a typed `form` prop also infers `TTransformedValues`.
  expectTypeOf(
    useFValues({ form: formP, parsed: true, defaultValues: { count: 42, toggle: true } }),
  ).toEqualTypeOf<FVParsed>()
  expectTypeOf(useFValues({ form: formP, parsed: true, name: 'count', defaultValues: 1 })).toEqualTypeOf<number>()

  // Silent subscription with a typed `form` prop infers callback arg.
  expectTypeOf(
    useFValues({ form, name: 'name' }, (v) => {
      expectTypeOf(v).toEqualTypeOf<string>()
    }),
  ).toEqualTypeOf<undefined>()
}

function _fValuesTypeChecks() {
  const form = null as unknown as UseFFormReturn<FV, FV>
  const formP = null as unknown as UseFFormReturn<FVRaw, FVParsed>

  // ---------------------------------------------------------------------------
  // RAW mode
  // ---------------------------------------------------------------------------

  void (
    <FValues
      form={form}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<DeepPartialSkipArrayKey<FV>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      compute={(v) => v.name.length}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<number>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      name="name"
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<string>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      name="age"
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<number>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      name="name"
      compute={(v) => v.toUpperCase()}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<string>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      name={['name', 'age'] as const}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<[string, number]>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      pick={['name'] as const}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<Pick<FV, 'name'>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      pick={['name', 'age'] as const}
      compute={(v) => v.age}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<number>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={form}
      omit={['name'] as const}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<Omit<FV, 'name'>>()
        return null
      }}
    />
  )

  // ---------------------------------------------------------------------------
  // PARSED mode
  // ---------------------------------------------------------------------------

  void (
    <FValues
      form={formP}
      parsed
      defaultValues={{ count: 0, toggle: false }}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<FVParsed>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<UseFValuesValidResult<DeepPartialSkipArrayKey<FVRaw>, FVParsed>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      compute={(v) => v.count + 1}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<UseFValuesValidComputedResult<number>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      name="count"
      defaultValues={0}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<number>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      name="count"
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<UseFValuesValidResult<string, number>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      pick={['count'] as const}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<UseFValuesValidPickResult<FVParsed, readonly ['count'], Pick<FVRaw, 'count'>>>()
        return null
      }}
    />
  )
  void (
    <FValues
      form={formP}
      parsed
      omit={['count'] as const}
      render={(v) => {
        expectTypeOf(v).toEqualTypeOf<UseFValuesValidResult<Omit<FVRaw, 'count'>, Omit<FVParsed, 'count'>>>()
        return null
      }}
    />
  )

  // ---------------------------------------------------------------------------
  // `children` instead of `render`
  // ---------------------------------------------------------------------------

  void (
    <FValues form={form} name="name">
      {(v) => {
        expectTypeOf(v).toEqualTypeOf<string>()
        return null
      }}
    </FValues>
  )

  // ---------------------------------------------------------------------------
  // No `form` prop → fall back to permissive defaults.
  // ---------------------------------------------------------------------------

  void (
    <FValues
      name="anything"
      render={(v) => {
        expectTypeOf(v).toBeAny()
        return null
      }}
    />
  )
  void (
    <FValues
      render={(v) => {
        // No form, no selector → DeepPartialSkipArrayKey<FieldValues>, which is a permissive object.
        expectTypeOf(v).toEqualTypeOf<DeepPartialSkipArrayKey<Record<string, any>>>()
        return null
      }}
    />
  )
}

// =============================================================================
// SECTION 2 — Runtime tests for `form.useValues`.
// =============================================================================

const flush = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

describe('form.useValues — raw mode (no `parsed`)', () => {
  test('no selector returns the full form values object', () => {
    let captured: { a: string; b: number } | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: 'hi', b: 2 } })
      const all = form.useValues()
      captured = all as { a: string; b: number }
      return <span data-testid="all">{JSON.stringify(all)}</span>
    }
    render(<Probe />)
    expect(captured).toEqual({ a: 'hi', b: 2 })
  })

  test('`name` (string) re-renders the consumer when that field changes', () => {
    let consumerRenders = 0
    let setName: ((v: string) => void) | undefined

    const Consumer = ({ form }: { form: ReturnType<typeof useFForm<{ a: string; b: string }>> }) => {
      const a = form.useValues({ name: 'a' })
      consumerRenders += 1
      return <span data-testid="a">{a}</span>
    }
    const Owner = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '1' } })
      setName = (v) => form.setValue('a', v)
      return <Consumer form={form} />
    }

    render(<Owner />)
    expect(screen.getByTestId('a').textContent).toBe('1')

    act(() => setName?.('2'))
    expect(screen.getByTestId('a').textContent).toBe('2')

    const renders = consumerRenders
    act(() => setName?.('2'))
    expect(consumerRenders).toBe(renders)
  })

  test('`name` (string) does NOT re-render the consumer when an unrelated field changes', () => {
    let consumerRenders = 0
    let setA: ((v: string) => void) | undefined
    let setB: ((v: string) => void) | undefined

    const Consumer = ({ form }: { form: ReturnType<typeof useFForm<{ a: string; b: string }>> }) => {
      const a = form.useValues({ name: 'a' })
      consumerRenders += 1
      return <span data-testid="a">{a}</span>
    }
    const Owner = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '1' } })
      setA = (v) => form.setValue('a', v)
      setB = (v) => form.setValue('b', v)
      return <Consumer form={form} />
    }

    render(<Owner />)
    const baseRenders = consumerRenders

    act(() => setB?.('changed'))
    expect(consumerRenders).toBe(baseRenders)
    expect(screen.getByTestId('a').textContent).toBe('1')

    act(() => setA?.('changed'))
    expect(consumerRenders).toBeGreaterThan(baseRenders)
    expect(screen.getByTestId('a').textContent).toBe('changed')
  })

  test('`name` (tuple) returns an array of field values in order', () => {
    let setA: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: '1', b: 2 } })
      setA = (v) => form.setValue('a', v)
      const tuple = form.useValues({ name: ['a', 'b'] as const })
      return <span data-testid="tuple">{JSON.stringify(tuple)}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('tuple').textContent).toBe('["1",2]')

    act(() => setA?.('zz'))
    expect(screen.getByTestId('tuple').textContent).toBe('["zz",2]')
  })

  test('`pick` returns only the selected top-level keys', () => {
    let setA: ((v: string) => void) | undefined
    let setC: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: 'A', b: 'B', c: 'C' } })
      setA = (v) => form.setValue('a', v)
      setC = (v) => form.setValue('c', v)
      const picked = form.useValues({ pick: ['a', 'b'] as const })
      return <span data-testid="picked">{JSON.stringify(picked)}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('picked').textContent).toBe('{"a":"A","b":"B"}')

    act(() => setA?.('AA'))
    expect(screen.getByTestId('picked').textContent).toBe('{"a":"AA","b":"B"}')

    // Picked field does not include `c`; updating it should not change output.
    const beforeC = screen.getByTestId('picked').textContent
    act(() => setC?.('CC'))
    expect(screen.getByTestId('picked').textContent).toBe(beforeC)
  })

  test('`omit` returns every top-level key except the omitted ones', () => {
    let setA: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: 'A', b: 'B', c: 'C' } })
      setA = (v) => form.setValue('a', v)
      const remaining = form.useValues({ omit: ['a'] as const })
      return <span data-testid="omit">{JSON.stringify(remaining)}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('omit').textContent).toBe('{"b":"B","c":"C"}')

    // Omitted field changes do NOT re-render the consumer's snapshot.
    const before = screen.getByTestId('omit').textContent
    act(() => setA?.('AA'))
    expect(screen.getByTestId('omit').textContent).toBe(before)
  })

  test('`compute` transforms the watched value on every render', () => {
    let setVal: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { x: 'abc' } })
      setVal = (v) => form.setValue('x', v)
      const upper = form.useValues({ name: 'x', compute: (v) => v.toUpperCase() })
      return <span data-testid="upper">{upper}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('upper').textContent).toBe('ABC')
    act(() => setVal?.('def'))
    expect(screen.getByTestId('upper').textContent).toBe('DEF')
  })

  test('`compute` (no selector) receives the full raw form values', () => {
    const received: unknown[] = []
    const Probe = () => {
      const form = useFForm({ defaultValues: { plan: 'basic', period: 'month' } })
      const plan = form.useValues({
        compute: (values) => {
          received.push(values)
          return values.plan
        },
      })
      return <span data-testid="plan">{plan}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('plan').textContent).toBe('basic')
    expect(received.every((value) => typeof value === 'object' && value !== null && 'plan' in value)).toBe(true)
  })

  test('`defaultValues` fill in when the watched value is undefined', () => {
    const Probe = () => {
      const form = useFForm<{ name: string | undefined }>({ defaultValues: { name: undefined } })
      const name = form.useValues({ name: 'name', defaultValues: 'fallback' })
      return <span data-testid="name">{name ?? '<undef>'}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('name').textContent).toBe('fallback')
  })

  test('`disabled: true` freezes the consumer at its initial snapshot', () => {
    let setVal: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { x: 'first' } })
      setVal = (v) => form.setValue('x', v)
      const x = form.useValues({ name: 'x', disabled: true })
      return <span data-testid="x">{x}</span>
    }
    render(<Probe />)
    expect(screen.getByTestId('x').textContent).toBe('first')
    act(() => setVal?.('second'))
    expect(screen.getByTestId('x').textContent).toBe('first')
  })
})

describe('form.useValues — parsed mode (`parsed: true`)', () => {
  const numberSchema = z.object({ count: z.coerce.number().int().min(0) })

  test('no selector + no defaultValues returns `{ isValid, parsed, original }`', async () => {
    let observed: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '7' },
      })
      const v = form.useValues({ parsed: true })
      observed = v
      return null
    }
    render(<Probe />)
    await flush()
    expect(observed).toMatchObject({ isValid: true, parsed: { count: 7 } })
    expect((observed as { original: { count: string } }).original).toEqual({ count: '7' })
  })

  test('no selector + defaultValues returns the parsed object directly (unwrapped)', async () => {
    let observed: { count: number } | undefined
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '3' },
      })
      const v = form.useValues({ parsed: true, defaultValues: { count: 0 } })
      observed = v as { count: number }
      return null
    }
    render(<Probe />)
    await flush()
    expect(observed).toEqual({ count: 3 })
  })

  test('name selector + no defaultValues returns the parsed scalar wrapped in a validity snapshot', async () => {
    let observed: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '4' },
      })
      const v = form.useValues({ parsed: true, name: 'count' })
      observed = v
      return null
    }
    render(<Probe />)
    await flush()
    // `parsed` projects the named field; `original` exposes the full raw values bag.
    expect((observed as { isValid: boolean }).isValid).toBe(true)
    expect((observed as { parsed: number }).parsed).toBe(4)
    expect((observed as { original: { count: string } }).original).toEqual({ count: '4' })
  })

  test('name selector + defaultValues returns the parsed value directly', async () => {
    let observed: number | undefined
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '12' },
      })
      const v = form.useValues({ parsed: true, name: 'count', defaultValues: 0 })
      observed = v as number
      return null
    }
    render(<Probe />)
    await flush()
    expect(observed).toBe(12)
  })

  test('compute (no defaults) returns `{ isValid, computed }`', async () => {
    let observed: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '5' },
      })
      const v = form.useValues({ parsed: true, compute: (vals) => vals.count + 1 })
      observed = v
      return null
    }
    render(<Probe />)
    await flush()
    expect(observed).toEqual({ isValid: true, computed: 6 })
  })

  test('initially invalid input reports `isValid: false` with undefined parsed', async () => {
    let observed: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: 'NaN' },
      })
      const v = form.useValues({ parsed: true })
      observed = v
      return null
    }
    render(<Probe />)
    await flush()
    expect((observed as { isValid: boolean }).isValid).toBe(false)
    expect((observed as { parsed: unknown }).parsed).toBeUndefined()
  })
})

describe('form.useValues — callback overloads (silent subscriptions)', () => {
  test('shorthand callback fires on any field change without re-rendering the host', () => {
    const cb = mock((_value: { x: string }) => {})
    let hostRenders = 0
    let setVal: ((v: string) => void) | undefined
    const Host = () => {
      hostRenders += 1
      const form = useFForm({ defaultValues: { x: '' } })
      setVal = (v) => form.setValue('x', v)
      form.useValues(cb as never)
      return null
    }
    render(<Host />)
    const baseRenders = hostRenders
    act(() => setVal?.('hello'))
    expect(cb).toHaveBeenCalled()
    expect(hostRenders).toBe(baseRenders)
  })

  test('`{ name }` + callback only fires for that field', () => {
    const cb = mock((_value: string) => {})
    let setA: ((v: string) => void) | undefined
    let setB: ((v: string) => void) | undefined
    const Host = () => {
      const form = useFForm({ defaultValues: { a: '', b: '' } })
      setA = (v) => form.setValue('a', v)
      setB = (v) => form.setValue('b', v)
      form.useValues({ name: 'a' }, cb as never)
      return null
    }
    render(<Host />)
    cb.mockClear()
    act(() => setB?.('changed'))
    expect(cb).not.toHaveBeenCalled()
    act(() => setA?.('changed'))
    expect(cb).toHaveBeenCalledTimes(1)
    expect(cb.mock.calls[0]?.[0]).toBe('changed')
  })

  test('`{ name }` + callback does NOT fire when the value is unchanged (value-based dedup)', () => {
    // Guarantees a consumer (e.g. the docs-search "Docs Searched" tracker) needs no last-value ref of its own: the
    // subscription only invokes the callback when the watched value actually changes, never on a same-value `setValue`.
    const cb = mock((_value: string) => {})
    let setA: ((v: string) => void) | undefined
    const Host = () => {
      const form = useFForm({ defaultValues: { a: 'same', b: '' } })
      setA = (v) => form.setValue('a', v)
      form.useValues({ name: 'a' }, cb as never)
      return null
    }
    render(<Host />)
    cb.mockClear()

    // Same value → no change → no fire.
    act(() => setA?.('same'))
    expect(cb).not.toHaveBeenCalled()

    // Real change → fires once.
    act(() => setA?.('changed'))
    expect(cb).toHaveBeenCalledTimes(1)

    // Re-setting the same new value → still no further fire.
    act(() => setA?.('changed'))
    expect(cb).toHaveBeenCalledTimes(1)
  })

  test('`{ pick }` + callback receives a picked object', () => {
    const cb = mock((_value: { a: string; b: string }) => {})
    let setA: ((v: string) => void) | undefined
    const Host = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '2', c: '3' } })
      setA = (v) => form.setValue('a', v)
      form.useValues({ pick: ['a', 'b'] as const }, cb as never)
      return null
    }
    render(<Host />)
    cb.mockClear()
    act(() => setA?.('11'))
    expect(cb).toHaveBeenCalledTimes(1)
    expect(cb.mock.calls[0]?.[0]).toMatchObject({ a: '11', b: '2' })
  })

  test('`{ omit }` + callback excludes the omitted keys', () => {
    const cb = mock((_value: { b: string; c: string }) => {})
    let setA: ((v: string) => void) | undefined
    let setB: ((v: string) => void) | undefined
    const Host = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '2', c: '3' } })
      setA = (v) => form.setValue('a', v)
      setB = (v) => form.setValue('b', v)
      form.useValues({ omit: ['a'] as const }, cb as never)
      return null
    }
    render(<Host />)
    cb.mockClear()
    // Omitted key change should not fire.
    act(() => setA?.('11'))
    expect(cb).not.toHaveBeenCalled()
    act(() => setB?.('22'))
    expect(cb).toHaveBeenCalledTimes(1)
    expect(cb.mock.calls[0]?.[0]).toMatchObject({ b: '22', c: '3' })
    expect((cb.mock.calls[0]?.[0] as Record<string, unknown>).a).toBeUndefined()
  })
})

// =============================================================================
// SECTION 3 — Runtime tests for `<FValues />`.
// =============================================================================

describe('<FValues /> — raw mode', () => {
  test('renders the watched value via `children` and uses surrounding FForm context', () => {
    let setName: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { name: 'Ada' } })
      setName = (v) => form.setValue('name', v)
      return (
        <FForm form={form}>
          <FValues name="name">{(name) => <span data-testid="name">{name}</span>}</FValues>
        </FForm>
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('name').textContent).toBe('Ada')
    act(() => setName?.('Grace'))
    expect(screen.getByTestId('name').textContent).toBe('Grace')
  })

  test('supports an explicit `form` and `render` prop', () => {
    let setCount: ((v: number) => void) | undefined
    const Consumer = ({ form }: { form: ReturnType<typeof useFForm<{ count: number }>> }) => (
      <FValues form={form} name="count" render={(count) => <span data-testid="count">{count}</span>} />
    )
    const Probe = () => {
      const form = useFForm({ defaultValues: { count: 1 } })
      setCount = (v) => form.setValue('count', v)
      return <Consumer form={form} />
    }
    render(<Probe />)
    expect(screen.getByTestId('count').textContent).toBe('1')
    act(() => setCount?.(2))
    expect(screen.getByTestId('count').textContent).toBe('2')
  })

  test('no selector → renders the full values object', () => {
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: 'A', b: 'B' } })
      return (
        <FForm form={form}>
          <FValues render={(values) => <span data-testid="all">{JSON.stringify(values)}</span>} />
        </FForm>
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('all').textContent).toBe('{"a":"A","b":"B"}')
  })

  test('`name` tuple → renders an array', () => {
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: '1', b: 2 } })
      return (
        <FValues
          form={form}
          name={['a', 'b'] as const}
          render={(tuple) => <span data-testid="tuple">{JSON.stringify(tuple)}</span>}
        />
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('tuple').textContent).toBe('["1",2]')
  })

  test('`pick` → renders only the selected keys', () => {
    let setC: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '2', c: '3' } })
      setC = (v) => form.setValue('c', v)
      return (
        <FValues
          form={form}
          pick={['a', 'b'] as const}
          render={(picked) => <span data-testid="picked">{JSON.stringify(picked)}</span>}
        />
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('picked').textContent).toBe('{"a":"1","b":"2"}')

    const before = screen.getByTestId('picked').textContent
    act(() => setC?.('33'))
    expect(screen.getByTestId('picked').textContent).toBe(before)
  })

  test('`omit` → renders without the omitted keys', () => {
    const Probe = () => {
      const form = useFForm({ defaultValues: { a: '1', b: '2', c: '3' } })
      return (
        <FValues
          form={form}
          omit={['a'] as const}
          render={(rest) => <span data-testid="rest">{JSON.stringify(rest)}</span>}
        />
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('rest').textContent).toBe('{"b":"2","c":"3"}')
  })

  test('`compute` transforms the watched value before rendering', () => {
    let setVal: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { x: 'abc' } })
      setVal = (v) => form.setValue('x', v)
      return (
        <FValues
          form={form}
          name="x"
          compute={(v) => v.toUpperCase()}
          render={(upper) => <span data-testid="upper">{upper}</span>}
        />
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('upper').textContent).toBe('ABC')
    act(() => setVal?.('xyz'))
    expect(screen.getByTestId('upper').textContent).toBe('XYZ')
  })

  test('conditional render based on a flag value (the ban.tsx pattern)', () => {
    let toggle: (() => void) | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { enabled: false, details: '' } })
      toggle = () => form.setValue('enabled', !form.getValues('enabled'))
      return (
        <FForm form={form}>
          <FValues name="enabled" render={(enabled) => (enabled ? <span data-testid="details">visible</span> : null)} />
        </FForm>
      )
    }
    render(<Probe />)
    expect(screen.queryByTestId('details')).toBeNull()
    act(() => toggle?.())
    expect(screen.getByTestId('details').textContent).toBe('visible')
    act(() => toggle?.())
    expect(screen.queryByTestId('details')).toBeNull()
  })
})

describe('<FValues /> — parsed mode', () => {
  const numberSchema = z.object({ count: z.coerce.number().int().min(0) })

  test('parsed + name + defaultValues renders the parsed scalar directly', async () => {
    let observed: ReactNode = null
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '9' },
      })
      return (
        <FValues
          form={form}
          parsed
          name="count"
          defaultValues={0}
          render={(count) => {
            observed = <span data-testid="parsed">{count}</span>
            return observed
          }}
        />
      )
    }
    render(<Probe />)
    await flush()
    expect(screen.getByTestId('parsed').textContent).toBe('9')
  })

  test('parsed + no defaults exposes `{ isValid, parsed, original }`', async () => {
    let captured: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '7' },
      })
      return (
        <FValues
          form={form}
          parsed
          name="count"
          render={(snapshot) => {
            captured = snapshot
            return <span data-testid="snap">{JSON.stringify(snapshot)}</span>
          }}
        />
      )
    }
    render(<Probe />)
    await flush()
    expect((captured as { isValid: boolean }).isValid).toBe(true)
    expect((captured as { parsed: number }).parsed).toBe(7)
    expect((captured as { original: { count: string } }).original).toEqual({ count: '7' })
  })

  test('parsed + compute renders the computed result (wrapped in `{ isValid, computed }` when no defaults)', async () => {
    let captured: unknown
    const Probe = () => {
      const form = useFForm<{ count: string }, { count: number }>({
        schema: numberSchema as never,
        defaultValues: { count: '4' },
      })
      return (
        <FValues
          form={form}
          parsed
          compute={(vals) => vals.count * 10}
          render={(result) => {
            captured = result
            return <span data-testid="comp">{JSON.stringify(result)}</span>
          }}
        />
      )
    }
    render(<Probe />)
    await flush()
    expect(captured).toEqual({ isValid: true, computed: 40 })
  })
})

describe('<FValues /> — render & children equivalence', () => {
  test('`children` and `render` produce the same output for the same selector', () => {
    const Probe = () => {
      const form = useFForm({ defaultValues: { name: 'Ada' } })
      return (
        <FForm form={form}>
          <FValues name="name" render={(v) => <span data-testid="render">{v}</span>} />
          <FValues name="name">{(v) => <span data-testid="children">{v}</span>}</FValues>
        </FForm>
      )
    }
    render(<Probe />)
    expect(screen.getByTestId('render').textContent).toBe('Ada')
    expect(screen.getByTestId('children').textContent).toBe('Ada')
  })
})
