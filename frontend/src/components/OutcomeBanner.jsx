import { formatUsd } from '../lib/format.js'
import Icon from './Icon.jsx'

const OUTCOMES = {
  FULL: { title: 'Paid in full', icon: 'check', style: 'border-success bg-success-container text-success' },
  PARTIAL: { title: 'Partially paid', icon: 'check', style: 'border-held bg-held-container text-held' },
  VOID: { title: 'Voided: the buyer was charged $0.00', icon: 'x', style: 'border-danger bg-danger-container text-danger' },
}

/** The decision, in one line, with the reason the arbiter gave. */
export default function OutcomeBanner({ decision }) {
  const outcome = OUTCOMES[decision.outcome] ?? OUTCOMES.VOID
  return (
    <div className={`flex items-start gap-3 rounded-lg border p-4 ${outcome.style}`} data-testid="outcome-banner">
      <Icon name={outcome.icon} className="mt-1 h-5 w-5 shrink-0" />
      <div>
        <p className="text-h2 font-semibold">{outcome.title}</p>
        <p className="mt-1 text-body-md">{decision.reason}</p>
        {decision.outcome !== 'VOID' && (
          <p className="tabular mt-1 text-body-sm">
            Captured {formatUsd(decision.capture_amount)} · worker {formatUsd(decision.worker_payout)} · fee {formatUsd(decision.platform_fee)}
          </p>
        )}
      </div>
    </div>
  )
}
