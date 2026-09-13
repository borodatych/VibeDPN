import { create } from 'zustand/react'

export const useAuthFormMemory = create<{
  value: { email: string; name: string }
  setValue: (value: { email?: string; name?: string }) => void
  reset: () => void
}>((set, get) => ({
  value: { email: '', name: '' },
  setValue: (value) => set({ value: { ...get().value, ...value } }),
  reset: () => set(useAuthFormMemory.getInitialState()),
}))
