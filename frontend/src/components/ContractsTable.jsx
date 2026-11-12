import { Link } from 'react-router'
import { formatDeadline, formatUsd, moneyState } from '../lib/format.js'
import { stateMeta } from '../lib/states.js'
import Icon from './Icon.jsx'
import StateChip from './StateChip.jsx'
import { Chip } from './ui.jsx'

const ACTION = { SETTLED: 'View receipt', VOIDED: 'View receipt' }

function actionFor(job) {
  const label = ACTION[job.state] ?? 'Open job'
  const to = ACTION[job.state] ? `/jobs/${job.job_id}/receipt` : `/jobs/${job.job_id}`
  return { label, to }
}

/** A compact list of jobs with their money state: a table from tablet width up, stacked cards on phones. */
export default function ContractsTable({ jobs }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-left text-body-sm">
          <thead className="bg-surface-muted text-label-caps uppercase tracking-label-caps text-text-muted">
            <tr>
              <th className="p-3">Job</th>
              <th className="p-3">Worker</th>
              <th className="p-3 text-right">Bounty</th>
              <th className="p-3">Money state</th>
              <th className="p-3">Stage</th>
              <th className="p-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const money = moneyState(job)
              const action = actionFor(job)
              return (
                <tr key={job.job_id} className="border-t border-border">
                  <td className="p-3">
                    <p className="font-semibold">{job.contract.specification.title}</p>
                    <p className="font-mono text-mono text-text-muted">{job.job_id}</p>
                  </td>
                  <td className="p-3 text-text-muted">{job.worker_id ?? '–'}</td>
                  <td className="tabular p-3 text-right font-mono font-semibold">{formatUsd(job.contract.bounty_usd)}</td>
                  <td className="p-3"><Chip tone={money.tone}>{money.label}</Chip></td>
                  <td className="p-3"><StateChip state={job.state} /></td>
                  <td className="p-3 text-right">
                    <Link to={action.to} className="inline-flex min-h-11 items-center gap-1 font-semibold text-tertiary hover:underline">
                      {action.label} <Icon name="arrow" className="h-3.5 w-3.5" />
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-border md:hidden">
        {jobs.map((job) => {
          const money = moneyState(job)
          const action = actionFor(job)
          return (
            <li key={job.job_id} className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold">{job.contract.specification.title}</p>
                  <p className="truncate font-mono text-mono text-text-muted">{job.job_id}</p>
                </div>
                <span className="tabular font-mono text-h3 font-bold">{formatUsd(job.contract.bounty_usd)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={money.tone}>{money.label}</Chip>
                <span className="text-body-sm text-text-muted">{stateMeta(job.state).label} · {formatDeadline(job.contract.deadline_epoch)}</span>
              </div>
              <Link to={action.to} className="inline-flex min-h-11 items-center gap-1 font-semibold text-tertiary">
                {action.label} <Icon name="arrow" className="h-3.5 w-3.5" />
              </Link>
            </li>
          )
        })}
      </ul>
    </>
  )
}
