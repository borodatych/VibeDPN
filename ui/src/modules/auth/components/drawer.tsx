import { useBreakpoint } from '@/components/hooks/use-breakpoint'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerTitle } from '@/components/ui/drawer'
import { SignInForm } from '@/modules/auth/components/sign-in'
import { X } from 'lucide-react'
import { useCallback } from 'react'
import { create } from 'zustand/react'

export type AuthDrawerState = {
  isOpen: boolean
  setIsOpen: (isOpen: boolean) => void
  description: string | null
  onSuccess: () => void
  open: (props?: { description?: string; onSuccess?: () => void }) => void
  close: () => void
}

export const useAuthDrawer = create<AuthDrawerState>((set, get) => ({
  isOpen: false,
  setIsOpen: (isOpen) => {
    if (!isOpen) {
      get().close()
    } else {
      get().open()
    }
  },
  description: null,
  onSuccess: () => {},
  open: (props) => {
    set({ isOpen: true, description: props?.description ?? null, onSuccess: props?.onSuccess ?? (() => {}) })
  },
  close: () => set(useAuthDrawer.getInitialState()),
}))

export const openAuthDrawer: AuthDrawerState['open'] = (...args) => useAuthDrawer.getState().open(...args)
export const closeAuthDrawer: AuthDrawerState['close'] = (...args) => useAuthDrawer.getState().close(...args)

export const AuthDrawer = () => {
  const { onSuccess, isOpen, setIsOpen, close, description } = useAuthDrawer()

  const handleSuccess = useCallback(() => {
    close()
    onSuccess()
  }, [close, onSuccess])

  const isSmOrLess = useBreakpoint('max-sm')
  const direction = isSmOrLess ? 'bottom' : 'right'

  return (
    <Drawer open={isOpen} onOpenChange={setIsOpen} direction={direction}>
      <DrawerContent rounded={isSmOrLess} wider>
        <div className="flex min-h-full flex-col overflow-y-auto p-7 *:last:mb-4 max-md:px-6 max-md:py-4">
          {!isSmOrLess && (
            <DrawerClose asChild className="fixed top-7 right-7 max-md:top-4 max-md:right-4">
              <Button variant="secondary" size="icon-lg" aria-label="Close auth drawer" icon={X} />
            </DrawerClose>
          )}
          <header className="mb-8 pr-14">
            <DrawerTitle className="font-title text-4xl leading-[1.1] font-semibold">Sign In</DrawerTitle>
            {description ? (
              <DrawerDescription className="mt-3 max-w-72 font-accent text-base leading-snug">
                {description}
              </DrawerDescription>
            ) : (
              <DrawerDescription className="sr-only" />
            )}
          </header>
          <SignInForm onSuccess={handleSuccess} />
        </div>
      </DrawerContent>
    </Drawer>
  )
}
