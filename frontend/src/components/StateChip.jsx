import { stateMeta } from '../lib/states.js'
import { Chip } from './ui.jsx'

const ICONS = {
  POSTED: 'doc', ACCEPTED: 'user', FUNDS_PENDING: 'clock', ESCROW_LOCKED: 'lock', SUBMITTED: 'code',
  ARBITRATING: 'scale', NEEDS_REVIEW: 'alert', SETTLING: 'bank', SETTLED: 'check', VOIDED: 'x', CANCELLED: 'x',
}

export default function StateChip({ state }) {
  const meta = stateMeta(state)
  return (
    <Chip tone={meta.tone} icon={ICONS[state]}>
      {meta.label}
    </Chip>
  )
}
