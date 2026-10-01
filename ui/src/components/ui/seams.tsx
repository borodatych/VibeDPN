/**
 * A thought the catalog splits at the seams of its meaning (`\n`): each part on a line of its own on a wide screen,
 * one paragraph on a phone — a line set for a wide column breaks into stubs in a narrow one
 *
 * The parts after the first may be written lowercase in the catalog: on a wide screen each starts with a capital
 *
 * @tags ui
 */
export const Seams = ({ text }: { text: string }) => {
  const parts = text.split('\n')
  return (
    <>
      {parts.map((part, index) => (
        <span key={index} className="md:block md:first-letter:uppercase">
          {index > 0 && <span className="md:hidden"> </span>}
          {part}
        </span>
      ))}
    </>
  )
}
