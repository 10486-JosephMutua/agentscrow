import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client.js'
import Icon from '../components/Icon.jsx'
import JobCard from '../components/JobCard.jsx'
import { ButtonLink, EmptyState, ErrorBanner, Page, Spinner } from '../components/ui.jsx'
import { formatUsd, moneyState } from '../lib/format.js'

const FILTERS = [
  { key: 'all', label: 'All', states: undefined },
  { key: 'open', label: 'Open', states: ['POSTED'] },
  { key: 'active', label: 'In progress', states: ['ACCEPTED', 'FUNDS_PENDING', 'ESCROW_LOCKED', 'SUBMITTED', 'ARBITRATING', 'NEEDS_REVIEW', 'SETTLING'] },
  { key: 'done', label: 'Finished', states: ['SETTLED', 'VOIDED', 'CANCELLED'] },
]

const SORTS = [
  { key: 'new', label: 'Newest first' },
  { key: 'high', label: 'Bounty: high to low' },
  { key: 'low', label: 'Bounty: low to high' },
]

function Stat({ label, value }) {
  return (
    <div className="rounded-md bg-neutral p-3">
      <p className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">{label}</p>
      <p className="tabular mt-1 font-mono text-h2 font-semibold">{value}</p>
    </div>
  )
}

export default function JobBoardPage() {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('new')
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState(null)
  const [mine, setMine] = useState({})

  const load = useCallback(async () => {
    try {
      const { states } = FILTERS.find((item) => item.key === filter)
      setJobs(await api.listJobs({ states, limit: 60 }))
      api.myJobs().then((items) => setMine(Object.fromEntries(items.map((item) => [item.job_id, item.roles.join(' + ')])))).catch(() => {})
      setError(null)
    } catch (err) {
      setError(err)
    }
  }, [filter])

  useEffect(() => {
    setJobs(null)
    load()
    const timer = setInterval(load, 8000)
    return () => clearInterval(timer)
  }, [load])

  const shown = useMemo(() => {
    if (!jobs) return null
    const needle = query.trim().toLowerCase()
    const matches = needle
      ? jobs.filter((job) => `${job.job_id} ${job.contract.specification.title} ${job.contract.specification.description}`.toLowerCase().includes(needle))
      : [...jobs]
    if (sort === 'high') matches.sort((a, b) => Number(b.contract.bounty_usd) - Number(a.contract.bounty_usd))
    if (sort === 'low') matches.sort((a, b) => Number(a.contract.bounty_usd) - Number(b.contract.bounty_usd))
    return matches
  }, [jobs, query, sort])

  const held = (jobs ?? []).reduce((sum, job) => sum + (moneyState(job).key === 'held' ? moneyState(job).amount : 0), 0)
  const total = (jobs ?? []).reduce((sum, job) => sum + Number(job.contract.bounty_usd), 0)

  return (
    <Page>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-1 basis-72">
          <h1 className="text-h1 font-bold">Job board</h1>
          <p className="mt-1 max-w-[36rem] text-text-muted">Every job is escrowed in PayPal before work starts. Automated test runners arbitrate the release, with no human delay.</p>
        </div>
        <ButtonLink variant="accent" to="/new"><Icon name="plus" /> Post a job</ButtonLink>
      </div>

      {jobs && (
        <div className="mt-5 grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface p-3 lg:grid-cols-3">
          <Stat label="Jobs shown" value={jobs.length} />
          <Stat label="Total bounty" value={formatUsd(total)} />
          <Stat label="Held in escrow" value={formatUsd(held)} />
        </div>
      )}

      {/* Static toolbar: stays under the app header while the list below scrolls. */}
      <div className="sticky top-0 z-10 -mx-4 mt-5 border-b border-border bg-neutral/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:pb-0" role="tablist" aria-label="Filter jobs">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                role="tab"
                aria-selected={filter === item.key}
                onClick={() => setFilter(item.key)}
                className={`min-h-11 shrink-0 rounded-full px-4 text-body-sm font-semibold ${filter === item.key ? 'bg-primary text-on-primary' : 'border border-border bg-surface hover:bg-surface-muted'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row lg:ml-auto">
            <label className="relative block min-w-0 flex-1 sm:w-64 sm:flex-none">
              <span className="sr-only">Filter by title or id</span>
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter by title or id…"
                className="min-h-11 w-full rounded-md border border-border bg-surface py-2 pl-9 pr-3 text-body-md"
              />
            </label>
            <label className="block">
              <span className="sr-only">Sort jobs</span>
              <select value={sort} onChange={(event) => setSort(event.target.value)} className="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-body-md sm:w-auto">
                {SORTS.map((item) => (
                  <option key={item.key} value={item.key}>{item.label}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        <ErrorBanner error={error} />
        {jobs === null && !error && <p className="flex items-center gap-2 text-text-muted"><Spinner /> Loading jobs…</p>}
        {jobs?.length === 0 && (
          <EmptyState icon="doc" title="No jobs here yet" action={<ButtonLink variant="accent" to="/new">Post the first job</ButtonLink>}>
            Post a job to see the whole escrow flow, from the PayPal hold to the verdict.
          </EmptyState>
        )}
        {jobs?.length > 0 && shown.length === 0 && <p className="text-text-muted">No jobs match “{query}”.</p>}
        {shown?.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((job) => (
              <JobCard key={job.job_id} job={job} role={mine[job.job_id]} />
            ))}
          </div>
        )}
      </div>
    </Page>
  )
}
