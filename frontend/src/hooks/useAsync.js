import { useCallback, useState } from 'react'

/**
 * Wraps an async action with busy/error state, for buttons.
 *   const [run, { busy, error }] = useAsyncAction(() => api.openEscrow(id))
 */
export function useAsyncAction(action) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const run = useCallback(
    async (...args) => {
      setBusy(true)
      setError(null)
      try {
        return await action(...args)
      } catch (err) {
        setError(err)
        return undefined
      } finally {
        setBusy(false)
      }
    },
    [action],
  )

  return [run, { busy, error, clearError: () => setError(null) }]
}
