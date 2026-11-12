import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getEvents, getJob, openTimeline } from '../api/client.js'
import { isTerminal } from '../lib/states.js'

/**
 * Loads a job and keeps it live: the timeline streams over SSE, and every new event refreshes the job.
 * Returns { job, events, error, loading, refresh, roles }: `roles` are what the server says this browser may do (job.viewer.roles).
 */
export function useJob(jobId) {
  const [job, setJob] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const lastEventId = useRef(0)
  const refreshTimer = useRef(null)

  const refresh = useCallback(async () => {
    try {
      setJob(await getJob(jobId))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'unknown', String(err)))
    } finally {
      setLoading(false)
    }
  }, [jobId])

  useEffect(() => {
    let closed = false
    let close = () => {}
    lastEventId.current = 0
    setEvents([])
    setLoading(true)
    ;(async () => {
      await refresh()
      try {
        const history = await getEvents(jobId, 0)
        if (closed) return
        if (history.length) lastEventId.current = history[history.length - 1].id
        setEvents(history)
      } catch {
        /* the stream below will fill the timeline in */
      }
      if (closed) return
      close = openTimeline(jobId, {
        after: lastEventId.current,
        onEvent: (event) => {
          if (event.id <= lastEventId.current) return
          lastEventId.current = event.id
          setEvents((current) => [...current, event])
          clearTimeout(refreshTimer.current)
          refreshTimer.current = setTimeout(refresh, 150) // coalesce bursts into one refresh
        },
      })
    })()
    return () => {
      closed = true
      close()
      clearTimeout(refreshTimer.current)
    }
  }, [jobId, refresh])

  // Safety net: if the stream is blocked (some proxies buffer SSE), poll while the job is still moving.
  useEffect(() => {
    if (!job || isTerminal(job.state)) return undefined
    const timer = setInterval(refresh, 4000)
    return () => clearInterval(timer)
  }, [job, refresh])

  return { job, events, error, loading, refresh, roles: job?.viewer?.roles ?? [] }
}
