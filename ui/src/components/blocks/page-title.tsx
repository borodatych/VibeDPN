import { Section } from '@/components/ui/section'
import type { ReactNode } from 'react'

/**
 * The title of a page and what it is for: the description runs the full width a step smaller than the pack sets it,
 * so a thought of it takes a line on a laptop and two thoughts two lines, not a narrow column of four
 *
 * @tags ui
 */
export const PageTitle = ({ title, description }: { title: string; description?: ReactNode }) => (
  <Section
    h1={title}
    description={description}
    descriptionClassName="max-w-none text-xl text-pretty max-md:text-lg max-sm:text-base"
  />
)
