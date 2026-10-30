import { useCallback, useEffect, useState } from 'react'

/** Fetch on mount and whenever deps change. Keeps the previous data while reloading. */
export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps)
  useEffect(() => {
    let alive = true
    setLoading(true)
    run()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [run, tick])
  return { data, error, loading, reload: () => setTick((t) => t + 1) }
}
