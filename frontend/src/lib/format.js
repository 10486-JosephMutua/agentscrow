export function formatUsd(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '$0.00'
  return number.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function formatScore(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '–'
}

export function shortId(id, keep = 6) {
  if (!id) return ''
  return id.length <= keep * 2 + 1 ? id : `${id.slice(0, keep)}…${id.slice(-keep)}`
}

export function formatTime(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatDateTime(iso) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

/** "in 3h 20m" / "2h 5m ago" for a unix-epoch (seconds) deadline. */
export function formatDeadline(epochSeconds, now = Date.now()) {
  const diffMs = epochSeconds * 1000 - now
  const minutes = Math.round(Math.abs(diffMs) / 60000)
  let text = `${minutes}m`
  if (minutes >= 1440) text = `${Math.round(minutes / 1440)}d`
  else if (minutes >= 60) text = `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  return diffMs >= 0 ? `in ${text}` : `${text} ago`
}

/**
 * What state is the money in? One answer per job, shown on every screen.
 * Returns { key, label, tone, amount } where tone matches the DESIGN.md status colors.
 */
export function moneyState(job) {
  const bounty = Number(job?.contract?.bounty_usd ?? 0)
  const decision = job?.decision
  switch (job?.state) {
    case 'ESCROW_LOCKED':
    case 'SUBMITTED':
    case 'ARBITRATING':
    case 'NEEDS_REVIEW':
      return { key: 'held', label: 'Held in escrow', tone: 'held', amount: bounty }
    case 'SETTLING':
      return { key: 'settling', label: 'Settling', tone: 'info', amount: bounty }
    case 'SETTLED':
      return decision?.outcome === 'PARTIAL'
        ? { key: 'partial', label: 'Partially paid', tone: 'success', amount: Number(decision.capture_amount) }
        : { key: 'paid', label: 'Paid out', tone: 'success', amount: Number(decision?.capture_amount ?? bounty) }
    case 'VOIDED':
      return { key: 'released', label: 'Released: buyer charged $0.00', tone: 'danger', amount: 0 }
    case 'FUNDS_PENDING':
      return { key: 'pending', label: 'Awaiting buyer approval', tone: 'warning', amount: bounty }
    default:
      return { key: 'none', label: 'Not held yet', tone: 'neutral', amount: bounty }
  }
}
