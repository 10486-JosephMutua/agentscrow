import { useEffect, useRef } from 'react'
import { formatTime } from '../lib/format.js'
import Icon from './Icon.jsx'

const KINDS = {
  state: { icon: 'dot', style: 'bg-surface-muted text-secondary' },
  mandate: { icon: 'shield', style: 'bg-tertiary-container text-tertiary' },
  paypal: { icon: 'bank', style: 'bg-held-container text-held' },
  webhook: { icon: 'bolt', style: 'bg-info-container text-info' },
  agent: { icon: 'user', style: 'bg-info-container text-info' },
  tier: { icon: 'scale', style: 'bg-info-container text-info' },
  decision: { icon: 'check', style: 'bg-success-container text-success' },
  error: { icon: 'alert', style: 'bg-danger-container text-danger' },
}

/** The live feed of everything that happened to this job and its money. */
export default function MoneyTimeline({ events }) {
  const list = useRef(null)
  useEffect(() => {
    // Scroll only the feed itself; scrollIntoView would also drag the surrounding page pane.
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [events.length])

  if (!events.length) return <p className="text-body-sm text-text-muted">Nothing has happened yet.</p>
  return (
    <ol ref={list} className="scroll-region max-h-96 space-y-3 pr-1" aria-live="polite" aria-label="Job timeline">
      {events.map((event) => {
        const kind = KINDS[event.kind] ?? KINDS.state
        const failed = event.kind === 'decision' && /VOID/.test(event.message)
        return (
          <li key={event.id} className="flex gap-3">
            <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${failed ? KINDS.error.style : kind.style}`}>
              <Icon name={failed ? 'x' : kind.icon} className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-body-md">{event.message}</p>
              <p className="font-mono text-mono text-text-muted">
                {formatTime(event.ts)} · {event.kind}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
