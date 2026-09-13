/**
 * High-level tests for the FForm primitives.
 *
 * The goal is to confirm that the public surface (`useFForm`, `form.useValues`, `<FForm>`, `FInput`, `FButton`) wires
 * up to react-hook-form correctly: subscribers re-render on the right keys, and submit/clear flow through `onSubmit` /
 * `onSuccess` as documented.
 */
// import { setupDomTestThings } from '@/test/setup/dom'
import { describe, expect, mock, test } from 'bun:test'
import { useRef } from 'react'
import { z } from 'zod'
import { FInput } from '../fields/input'
import { FButton } from './button'
import { useFForm } from './hook'
import { FFields, FFooter } from './layout'
import { FForm } from './provider'
import { act, fireEvent, render, screen } from '@testing-library/react'

// const { act, fireEvent, render, screen } = await setupDomTestThings()

const flush = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

describe('useFForm — handle identity & basic state', () => {
  test('returns a stable handle across re-renders', () => {
    const handles: unknown[] = []
    const Probe = () => {
      const form = useFForm({ defaultValues: { name: '' } })
      handles.push(form)
      return <button onClick={() => form.setValue('name', 'a')}>tick</button>
    }
    render(<Probe />)
    act(() => {
      screen.getByText('tick').click()
    })
    expect(handles.length).toBeGreaterThanOrEqual(2)
    expect(handles[0]).toBe(handles[handles.length - 1])
  })

  test('getValues / setValue round-trip work without a schema', () => {
    let captured: ReturnType<typeof useFForm<{ name: string }>> | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { name: 'hi' } })
      captured = form
      return null
    }
    render(<Probe />)
    expect(captured?.getValues().name).toBe('hi')
    act(() => {
      captured?.setValue('name', 'bye')
    })
    expect(captured?.getValues().name).toBe('bye')
  })
})

describe('<FForm>, FInput, FButton — end-to-end', () => {
  test('FInput is wired to the form; submitting passes parsed values to onSubmit', async () => {
    const onSubmit = mock(async (_parsed: { name: string }) => {})
    render(
      <FForm
        schema={z.object({ name: z.string().min(1) })}
        defaultValues={{ name: '' }}
        onSubmit={onSubmit as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="name" label="Name" placeholder="Your name" />
        </FFields>
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )

    const input = screen.getByPlaceholderText('Your name') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Alice' } })
    expect(input.value).toBe('Alice')

    const formEl = input.closest('form')!
    fireEvent.submit(formEl)
    await flush()
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect((onSubmit.mock.calls[0] as unknown[])[0]).toMatchObject({ name: 'Alice' })
  })

  test('FInput respects valueAsNumber when registering with RHF', async () => {
    const onSubmit = mock(async (_parsed: { age: number }, _original: { age: number }) => {})
    render(
      <FForm
        schema={z.object({ age: z.number() })}
        defaultValues={{ age: undefined }}
        onSubmit={onSubmit as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="age" type="number" placeholder="Age" valueAsNumber />
        </FFields>
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )

    const input = screen.getByPlaceholderText('Age') as HTMLInputElement
    fireEvent.change(input, { target: { value: '42' } })
    fireEvent.submit(input.closest('form')!)
    await flush()

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect((onSubmit.mock.calls[0] as unknown[])[0]).toMatchObject({ age: 42 })
    expect((onSubmit.mock.calls[0] as unknown[])[1]).toMatchObject({ age: 42 })
  })

  test('FInput respects valueAsDate when registering with RHF', async () => {
    const onSubmit = mock(async (_parsed: { startsOn: Date }, _original: { startsOn: Date }) => {})
    render(
      <FForm
        schema={z.object({ startsOn: z.date() })}
        defaultValues={{ startsOn: undefined }}
        onSubmit={onSubmit as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="startsOn" type="date" placeholder="Start date" valueAsDate />
        </FFields>
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )

    const input = screen.getByPlaceholderText('Start date') as HTMLInputElement
    fireEvent.change(input, { target: { value: '2026-05-25' } })
    fireEvent.submit(input.closest('form')!)
    await flush()

    const parsed = (onSubmit.mock.calls[0] as unknown[] | undefined)?.[0] as { startsOn: Date } | undefined
    const original = (onSubmit.mock.calls[0] as unknown[] | undefined)?.[1] as { startsOn: Date } | undefined

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(parsed?.startsOn).toBeInstanceOf(Date)
    expect(original?.startsOn).toBeInstanceOf(Date)
    expect(parsed?.startsOn.toISOString()).toBe('2026-05-25T00:00:00.000Z')
    expect(original?.startsOn.toISOString()).toBe('2026-05-25T00:00:00.000Z')
  })

  test('schema-invalid submit does NOT call onSubmit', async () => {
    const onSubmit = mock(async () => {})
    render(
      <FForm
        schema={z.object({ name: z.string().min(1) })}
        defaultValues={{ name: '' }}
        onSubmit={onSubmit as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )
    fireEvent.submit(screen.getByText('Submit').closest('form')!)
    await flush()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  test('onSettled is called with success details after a successful submit', async () => {
    const onSubmit = mock(async () => 'saved')
    const onSettled = mock((_result: unknown) => {})
    render(
      <FForm
        schema={z.object({ name: z.string().min(1) })}
        defaultValues={{ name: 'Alice' }}
        onSubmit={onSubmit as never}
        onSettled={onSettled as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )

    fireEvent.submit(screen.getByText('Submit').closest('form')!)
    await flush()

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSettled).toHaveBeenCalledTimes(1)
    expect(onSettled.mock.calls[0]?.[0]).toMatchObject({
      status: 'success',
      submitOutput: 'saved',
      inputParsed: { name: 'Alice' },
      inputOriginal: { name: 'Alice' },
    })
  })

  test('onSettled is called with the submit error after a failed submit', async () => {
    const submitError = new Error('submit failed')
    const onSubmit = mock(async () => {
      throw submitError
    })
    const onSubmitError = mock((_error: unknown) => {})
    const onSettled = mock((_result: unknown) => {})
    render(
      <FForm
        defaultValues={{ name: 'Alice' }}
        onSubmit={onSubmit as never}
        onSubmitError={onSubmitError}
        onSettled={onSettled as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )

    fireEvent.submit(screen.getByText('Submit').closest('form')!)
    await flush()

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmitError).toHaveBeenCalledTimes(1)
    expect(onSettled).toHaveBeenCalledTimes(1)
    expect(onSettled.mock.calls[0]?.[0]).toMatchObject({
      status: 'error',
      error: onSubmitError.mock.calls[0]?.[0],
    })
  })

  test('clearFormOnSuccess resets values after successful submit', async () => {
    const onSubmit = mock(async () => {})
    render(
      <FForm
        defaultValues={{ name: '' }}
        onSubmit={onSubmit as never}
        toastOnSuccess={false}
        toastOnValidationError={false}
        clearFormOnSuccess
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="name" placeholder="Name" />
        </FFields>
        <FFooter>
          <FButton type="submit">Submit</FButton>
        </FFooter>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Name') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'Alice' } })
    fireEvent.submit(input.closest('form')!)
    await flush()
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(input.value).toBe('')
  })
})

describe('useFForm({ use }) — setup hook for the typed form', () => {
  test('runs the `use` callback against the typed form so hooks can be wired inline', () => {
    const cb = mock((_value: string) => {})
    let setName: ((v: string) => void) | undefined
    const Probe = () => {
      const form = useFForm({
        defaultValues: { name: '' },
        use: (f) => {
          f.useValues({ name: 'name' }, cb)
        },
      })
      setName = (v) => form.setValue('name', v)
      return null
    }
    render(<Probe />)
    cb.mockClear()
    act(() => setName?.('alice'))
    expect(cb).toHaveBeenCalledTimes(1)
    expect(cb.mock.calls[0]?.[0]).toBe('alice')
  })
})

describe('form.useSubscribe — RHF subscribe wrapped in useEffect', () => {
  test('fires the callback for matching changes and does not re-render host', () => {
    const cb = mock((_data: { values: { a: string; b: string } }) => {})
    let hostRenders = 0
    let setA: ((v: string) => void) | undefined
    let setB: ((v: string) => void) | undefined

    const Host = () => {
      hostRenders += 1
      const form = useFForm({ defaultValues: { a: '', b: '' } })
      setA = (v) => form.setValue('a', v)
      setB = (v) => form.setValue('b', v)
      form.useSubscribe({
        name: ['a'],
        formState: { values: true },
        callback: cb as never,
      })
      return null
    }

    render(<Host />)
    cb.mockClear()
    const baseRenders = hostRenders
    act(() => setB?.('ignored'))
    expect(cb).not.toHaveBeenCalled()
    act(() => setA?.('hit'))
    expect(cb).toHaveBeenCalledTimes(1)
    expect(hostRenders).toBe(baseRenders)
  })
})

describe('form.id — propagation to form element and field ids', () => {
  test('useFForm({ id }) exposes the id on the returned handle', () => {
    let captured: ReturnType<typeof useFForm<{ name: string }>> | undefined
    const Probe = () => {
      const form = useFForm({ id: 'login', defaultValues: { name: '' } })
      captured = form
      return null
    }
    render(<Probe />)
    expect(captured?.id).toBe('login')
  })

  test('useFForm without id leaves form.id undefined', () => {
    let captured: ReturnType<typeof useFForm<{ name: string }>> | undefined
    const Probe = () => {
      const form = useFForm({ defaultValues: { name: '' } })
      captured = form
      return null
    }
    render(<Probe />)
    expect(captured?.id).toBeUndefined()
  })

  test('<FForm id> sets the id on the underlying <form> element', () => {
    render(
      <FForm
        id="signup"
        defaultValues={{ name: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="name" placeholder="Name" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Name') as HTMLInputElement
    const formEl = input.closest('form')!
    expect(formEl.id).toBe('signup')
  })

  test('user-supplied formProps.id wins over form.id on the <form> element', () => {
    render(
      <FForm
        id="from-hook"
        formProps={{ id: 'from-props' }}
        defaultValues={{ name: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="name" placeholder="Name" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Name') as HTMLInputElement
    const formEl = input.closest('form')!
    expect(formEl.id).toBe('from-props')
  })

  test('FInput receives id = `${form.id}-${name}` when form.id is set', () => {
    render(
      <FForm
        id="profile"
        defaultValues={{ email: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="email" placeholder="Email" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Email') as HTMLInputElement
    expect(input.id).toBe('profile-email')
  })

  test('FInput id falls back to name when form.id is unset', () => {
    render(
      <FForm
        defaultValues={{ email: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="email" placeholder="Email" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Email') as HTMLInputElement
    expect(input.id).toBe('email')
  })

  test('explicit FInput id wins over form.id prefix', () => {
    render(
      <FForm
        id="profile"
        defaultValues={{ email: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput id="custom-email" name="email" placeholder="Email" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Email') as HTMLInputElement
    expect(input.id).toBe('custom-email')
  })

  test('FieldLabel htmlFor matches the prefixed input id', () => {
    render(
      <FForm
        id="profile"
        defaultValues={{ email: '' }}
        onSubmit={async () => {}}
        toastOnSuccess={false}
        toastOnValidationError={false}
        toastOnSubmitError={false}
      >
        <FFields>
          <FInput name="email" label="Email" placeholder="Email" />
        </FFields>
      </FForm>,
    )
    const input = screen.getByPlaceholderText('Email') as HTMLInputElement
    expect(input.id).toBe('profile-email')
    const label = screen.getByText('Email').closest('label')!
    expect(label.getAttribute('for')).toBe('profile-email')
  })
})

describe('Stable hook identity sanity', () => {
  test('form.useValues / form.useSubscribe references on the handle are stable', () => {
    const seen = {
      useValues: new Set<unknown>(),
      useSubscribe: new Set<unknown>(),
    }
    const Probe = () => {
      const renders = useRef(0)
      const form = useFForm({ defaultValues: { x: '' } })
      seen.useValues.add(form.useValues)
      seen.useSubscribe.add(form.useSubscribe)
      renders.current += 1
      return (
        <button data-testid="bump" onClick={() => form.setValue('x', String(Math.random()))}>
          bump
        </button>
      )
    }
    render(<Probe />)
    act(() => {
      screen.getByTestId('bump').click()
    })
    act(() => {
      screen.getByTestId('bump').click()
    })
    expect(seen.useValues.size).toBe(1)
    expect(seen.useSubscribe.size).toBe(1)
  })
})
