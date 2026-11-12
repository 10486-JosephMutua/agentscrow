import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import * as api from '../api/client.js'
import StateChip from '../components/StateChip.jsx'
import { Button, Card, EmptyState, ErrorBanner, Page, PageTitle } from '../components/ui.jsx'
import { useAsyncAction } from '../hooks/useAsync.js'
import { formatUsd } from '../lib/format.js'

const INPUT = 'w-full rounded-md border border-border bg-surface px-3 py-2 text-body-md'

function TokenGate({ onSaved }) {
  const [value, setValue] = useState('')
  const [login, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.adminLogin(value.trim())
    setValue('')
    onSaved()
  })
  return (
    <Page narrow="max-w-[28rem]">
      <EmptyState icon="lock" title="Operator access">
        Enter the ADMIN_TOKEN configured on the server. It is exchanged for a secure session cookie that page scripts cannot read.
      </EmptyState>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          login()
        }}
      >
        <input type="password" aria-label="Operator token" className={`${INPUT} min-w-0`} value={value} onChange={(event) => setValue(event.target.value)} autoComplete="off" />
        <Button type="submit" busy={busy} disabled={!value.trim()}>Unlock</Button>
      </form>
      <div className="mt-3"><ErrorBanner error={error} onDismiss={clearError} /></div>
    </Page>
  )
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">{label}</p>
      <p className="tabular mt-1 text-h1 font-bold">{value}</p>
    </div>
  )
}

export default function OpsPage() {
  const [unlocked, setUnlocked] = useState(true) // optimistic: the first request tells us whether the session is valid
  const [overview, setOverview] = useState(null)
  const [jobs, setJobs] = useState([])
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      if (!(await api.whoami()).admin) {
        setUnlocked(false)
        return
      }
      const [summary, list] = await Promise.all([api.adminOverview(), api.adminJobs()])
      setOverview(summary)
      setJobs(list)
      setError(null)
    } catch (err) {
      setError(err)
      if (err.status === 401 || err.status === 403) {
        setUnlocked(false)
        setError(null)
      }
    }
  }, [])

  useEffect(() => {
    if (unlocked) load()
  }, [unlocked, load])

  const [sweep, sweepState] = useAsyncAction(async () => {
    await api.adminSweep()
    await load()
  })
  const [retry, retryState] = useAsyncAction(async (jobId) => {
    await api.arbitrateJob(jobId)
    await load()
  })

  if (!unlocked) {
    return (
      <Page>
        <ErrorBanner error={error} />
        <TokenGate onSaved={() => setUnlocked(true)} />
      </Page>
    )
  }

  const counts = overview?.counts ?? {}
  const stuck = jobs.filter((job) => ['NEEDS_REVIEW', 'SETTLING', 'SUBMITTED'].includes(job.state))
  return (
    <Page>
      <PageTitle title="Operator" subtitle="What needs attention, and where the money went.">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" busy={sweepState.busy} onClick={sweep}>Close overdue jobs</Button>
          <Button variant="secondary" onClick={async () => { await api.adminLogout(); setUnlocked(false) }}>Lock</Button>
        </div>
      </PageTitle>
      <div className="space-y-6">
        <ErrorBanner error={error ?? sweepState.error ?? retryState.error} />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Captured" value={formatUsd(overview?.captured_usd)} />
          <Stat label="Paid to workers" value={formatUsd(overview?.paid_to_workers_usd)} />
          <Stat label="Platform fees" value={formatUsd(overview?.platform_fees_usd)} />
          <Stat label="Jobs settled / voided" value={`${counts.SETTLED ?? 0} / ${counts.VOIDED ?? 0}`} />
        </div>

        <Card title={`Needs attention (${stuck.length})`}>
          {stuck.length === 0 ? (
            <p className="text-body-sm text-text-muted">Nothing is stuck.</p>
          ) : (
            <ul className="divide-y divide-border">
              {stuck.map((job) => (
                <li key={job.job_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div>
                    <Link className="font-semibold text-tertiary underline" to={`/jobs/${job.job_id}`}>{job.contract.specification.title}</Link>
                    <p className="font-mono text-mono text-text-muted">{job.job_id}</p>
                    {job.error && <p className="text-body-sm text-danger">{job.error}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <StateChip state={job.state} />
                    <Button variant="secondary" onClick={() => retry(job.job_id)} busy={retryState.busy}>Retry</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="All jobs">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-body-sm">
              <thead className="bg-surface-muted text-label-caps uppercase tracking-label-caps text-text-muted">
                <tr><th className="p-2">Job</th><th className="p-2">State</th><th className="p-2">Bounty</th><th className="p-2">Worker</th></tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.job_id} className="border-b border-border">
                    <td className="p-2"><Link className="font-mono text-mono text-tertiary underline" to={`/jobs/${job.job_id}`}>{job.job_id}</Link></td>
                    <td className="p-2"><StateChip state={job.state} /></td>
                    <td className="tabular p-2">{formatUsd(job.contract.bounty_usd)}</td>
                    <td className="p-2">{job.worker_id ?? '–'} {job.worker_email && <span className="text-text-muted">({job.worker_email})</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </Page>
  )
}
