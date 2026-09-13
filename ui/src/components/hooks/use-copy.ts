import copyToClipboard from 'copy-to-clipboard'
import { useCallback, useEffect, useState } from 'react'

export const useCopy = () => {
  const [copied, setCopied] = useState(0)

  const copy: typeof copyToClipboard = useCallback(async (...args) => {
    return await copyToClipboard(...args).then((result) => {
      setCopied(Math.random() + 1)
      return result
    })
  }, [])

  useEffect(() => {
    if (!copied) {
      return
    }
    const timeout = setTimeout(() => setCopied(0), 1500)
    return () => clearTimeout(timeout)
  }, [copied])
  return { copied: !!copied, copy }
}
