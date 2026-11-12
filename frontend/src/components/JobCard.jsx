import { Link } from 'react-router'
import { formatDeadline, formatUsd, moneyState } from '../lib/format.js'
import StateChip from './StateChip.jsx'
import Icon from './Icon.jsx'
import { Chip } from './ui.jsx'

/** One job on the board: state, what it is, and where the money is. */
export default function JobCard({ job, role }) {
  const spec = job.contract.specification
  const money = moneyState(job)
  const finished = ['SETTLED', 'VOIDED', 'CANCELLED'].includes(job.state)
  return (
    <Link
      to={`/jobs/${job.job_id}`}
      className="group flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface p-5 transition hover:border-tertiary hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 truncate font-mono text-mono text-text-muted">{job.job_id}</p>
        <StateChip state={job.state} />
      </div>
      <h3 className="text-h2 font-semibold group-hover:text-tertiary">{spec.title}</h3>
      <p className="line-clamp-2 text-body-sm text-text-muted">{spec.description}</p>
      <code className="block truncate rounded bg-surface-muted px-2 py-1 font-mono text-mono text-secondary">{spec.function_signature}</code>
      <div className="mt-auto flex flex-wrap items-end justify-between gap-x-3 gap-y-2 border-t border-border pt-3">
        <div>
          <p className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">{finished ? 'Settled amount' : 'Escrow bounty'}</p>
          <p className="tabular font-mono text-h2 font-bold">{formatUsd(finished ? money.amount : job.contract.bounty_usd)}</p>
        </div>
        <div className="flex flex-col items-end gap-1 text-body-sm text-text-muted">
          <span className="flex items-center gap-1"><Icon name="clock" className="h-3.5 w-3.5" /> {formatDeadline(job.contract.deadline_epoch)}</span>
          <Chip tone={money.tone}>{money.label}</Chip>
        </div>
      </div>
      {role && <span className="self-start rounded-full bg-surface-muted px-2 py-0.5 text-label-caps font-semibold uppercase tracking-label-caps">{role}</span>}
    </Link>
  )
}
