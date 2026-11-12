import { formatUsd, moneyState } from '../lib/format.js'
import { Chip } from './ui.jsx'

const ICON = { held: 'lock', paid: 'check', partial: 'check', released: 'x', pending: 'clock', settling: 'bank', none: 'dot' }
const RING = {
  held: 'border-held bg-held-container', paid: 'border-success bg-success-container', partial: 'border-success bg-success-container',
  released: 'border-danger bg-danger-container', pending: 'border-warning bg-warning-container', settling: 'border-info bg-info-container',
  none: 'border-border bg-surface',
}

/** The one thing every screen answers first: how much money, in what state. */
export default function MoneyCard({ job }) {
  const money = moneyState(job)
  const decision = job.decision
  return (
    <div className={`rounded-lg border p-5 ${RING[money.key]}`} aria-live="polite">
      <Chip tone={money.tone} icon={ICON[money.key]}>
        {money.label}
      </Chip>
      <p className="tabular mt-3 text-display font-bold" data-testid="money-amount">
        {formatUsd(money.amount)}
      </p>
      <p className="mt-1 text-body-sm text-text-muted">of a {formatUsd(job.contract.bounty_usd)} bounty</p>
      {decision && decision.outcome !== 'VOID' && (
        <dl className="tabular mt-4 grid grid-cols-2 gap-y-1 border-t border-border pt-3 text-body-sm">
          <dt className="text-text-muted">Worker receives</dt>
          <dd className="text-right font-semibold">{formatUsd(decision.worker_payout)}</dd>
          <dt className="text-text-muted">Platform fee</dt>
          <dd className="text-right font-semibold">{formatUsd(decision.platform_fee)}</dd>
        </dl>
      )}
    </div>
  )
}
