import { useState } from 'react'
import { Link, useOutletContext, useParams, useSearchParams } from 'react-router'
import ActionPanel from '../components/ActionPanel.jsx'
import CodeBlock from '../components/CodeBlock.jsx'
import Icon from '../components/Icon.jsx'
import MoneyCard from '../components/MoneyCard.jsx'
import MoneyTimeline from '../components/MoneyTimeline.jsx'
import OutcomeBanner from '../components/OutcomeBanner.jsx'
import ScoreGauge from '../components/ScoreGauge.jsx'
import SiteChecklist from '../components/SiteChecklist.jsx'
import SitePreview from '../components/SitePreview.jsx'
import StateChip from '../components/StateChip.jsx'
import StateStepper from '../components/StateStepper.jsx'
import TierCards from '../components/TierCards.jsx'
import { Card, EmptyState, ErrorBanner, MonoId, Page, Pane, Panes, Spinner } from '../components/ui.jsx'
import { useJob } from '../hooks/useJob.js'
import { formatDeadline, formatUsd } from '../lib/format.js'
import { stateMeta } from '../lib/states.js'

const ROLE_LABELS = { buyer: 'Buyer', worker: 'Worker', admin: 'Operator', public: 'Guest' }

function RoleSwitcher({ roles, acting, onChange }) {
  if (roles.length < 2) return <span className="rounded-full bg-surface-muted px-3 py-1 text-body-sm font-semibold">Viewing as {ROLE_LABELS[acting]}</span>
  return (
    <div className="inline-flex rounded-full border border-border bg-surface p-1" role="tablist" aria-label="Act as">
      {roles.map((role) => (
        <button
          key={role}
          role="tab"
          aria-selected={acting === role}
          onClick={() => onChange(role)}
          className={`rounded-full px-3 py-1 text-body-sm font-semibold ${acting === role ? 'bg-primary text-on-primary' : 'text-text-muted hover:text-text'}`}
        >
          {ROLE_LABELS[role]}
        </button>
      ))}
    </div>
  )
}

function Brief({ job }) {
  const spec = job.contract.specification
  return (
    <Card title="The job">
      <h2 className="text-h2 font-semibold">{spec.title}</h2>
      <p className="mt-2 text-body-md">{spec.description}</p>
      {!spec.preferences && <p className="mt-3 break-all rounded bg-surface-muted p-2 font-mono text-mono">{spec.function_signature}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-body-sm text-text-muted">
        <Icon name="shield" className="h-4 w-4" /> {spec.preferences ? 'Preference checks committed:' : 'Hidden tests committed:'}
        <MonoId value={job.contract.hidden_tests_sha256} label="hidden test commitment" />
      </div>
      <h3 className="mt-4 text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">Acceptance criteria</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-body-md">
        {spec.acceptance_criteria.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {!spec.preferences && (
        <details className="mt-4">
          <summary className="cursor-pointer text-body-sm font-semibold">Public example tests (the buyer also holds hidden ones)</summary>
          <div className="mt-2"><CodeBlock code={spec.public_tests} label="Public example tests" /></div>
        </details>
      )}
    </Card>
  )
}

function Verdict({ job }) {
  const website = Boolean(job.verdict.checklist)
  return (
    <Card title="Arbiter verdict">
      <div className="space-y-6">
        {job.decision && <OutcomeBanner decision={job.decision} />}
        <div className="grid items-center gap-6 md:grid-cols-[220px_1fr]">
          <ScoreGauge value={job.verdict.v_score} />
          <p className="text-body-sm text-text-muted">
            {website
              ? 'V = 0.30 × schema + 0.40 × preference checks + 0.30 × tone judge. Any failed gate voids the hold, whatever the score. Paid in full at V ≥ 0.85 with every check met, pro-rated from 0.50.'
              : 'V = 0.30 × schema + 0.40 × hidden tests + 0.30 × semantic judge. Any failed gate voids the hold, whatever the score. Paid in full at V ≥ 0.85 with every test passing, pro-rated from 0.50.'}
          </p>
        </div>
        <TierCards verdict={job.verdict} />
        {website && (
          <div>
            <h3 className="mb-3 text-h3 font-semibold">Does it fulfil what the buyer wanted?</h3>
            <SiteChecklist items={job.verdict.checklist} />
          </div>
        )}
      </div>
    </Card>
  )
}

function Deliverable({ job }) {
  if (!job.deliverable) {
    return job.deliverable_submitted ? (
      <Card title="Deliverable"><p className="text-body-sm text-text-muted">A deliverable was submitted. Only the buyer and worker can read it.</p></Card>
    ) : null
  }
  if (job.deliverable.index_html) {
    return (
      <Card title="Deliverable: the website">
        <SitePreview html={job.deliverable.index_html} title={`${job.contract.specification.title} (worker's delivery)`} />
        <details className="mt-4">
          <summary className="cursor-pointer text-body-sm font-semibold">View the HTML source</summary>
          <div className="mt-2"><CodeBlock code={job.deliverable.index_html} label="Submitted index.html" /></div>
        </details>
        <p className="mt-3 text-body-sm text-text-muted"><b className="text-text">Worker's explanation:</b> {job.deliverable.explanation}</p>
      </Card>
    )
  }
  return (
    <Card title="Deliverable">
      <CodeBlock code={job.deliverable.solution_code} label="Submitted solution" />
      <p className="mt-3 text-body-sm text-text-muted"><b className="text-text">Worker's explanation:</b> {job.deliverable.explanation}</p>
    </Card>
  )
}

function PayPalIds({ job }) {
  const rows = [
    ['PayPal order', job.order_id],
    ['Authorization', job.authorization_id],
    ['Capture', job.capture_id],
    ['Payout batch', job.payout_batch_id],
  ].filter(([, value]) => value)
  if (!rows.length) return null
  return (
    <Card title="PayPal references">
      <dl className="space-y-2 text-body-sm">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-text-muted">{label}</dt>
            <dd><MonoId value={value} label={label} /></dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

export default function JobPage() {
  const { jobId } = useParams()
  const [search] = useSearchParams()
  const { health } = useOutletContext() ?? {}
  const { job, events, error, loading, refresh, roles } = useJob(jobId)
  const [chosen, setChosen] = useState(null)
  const acting = roles.includes(chosen) ? chosen : (roles[0] ?? 'public')

  if (loading && !job) return <Page><p className="flex items-center gap-2 text-text-muted"><Spinner /> Loading job…</p></Page>
  if (error?.status === 404) {
    return <Page><EmptyState icon="alert" title="Job not found" action={<Link className="font-semibold text-tertiary underline" to="/jobs">Back to the job board</Link>}>No job has the id {jobId}.</EmptyState></Page>
  }
  if (!job) return <Page><ErrorBanner error={error} /></Page>

  const spec = job.contract.specification
  const meta = stateMeta(job.state)
  const finished = ['SETTLED', 'VOIDED'].includes(job.state)

  const top = (
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-h2 font-bold sm:text-h1">{spec.title}</h1>
          <StateChip state={job.state} />
        </div>
        <p className="text-body-sm text-text-muted">
          {meta.hint} · bounty <b className="tabular text-text">{formatUsd(job.contract.bounty_usd)}</b><span className="hidden sm:inline"> · due {formatDeadline(job.contract.deadline_epoch)}</span>
        </p>
        <div className="hidden sm:block"><MonoId value={job.job_id} label="job id" /></div>
      </div>
      <RoleSwitcher roles={roles.length ? roles : ['public']} acting={acting} onChange={setChosen} />
    </header>
  )

  return (
    <Panes top={top} className="lg:grid-cols-[minmax(0,1fr)_360px]">
      {/* Left column: the story of the job. Scrolls on its own on desktop. */}
      <Pane className="space-y-6">
        {search.get('funded') && job.state === 'ESCROW_LOCKED' && <div role="status" className="rounded-md border border-success bg-success-container p-3 text-body-sm text-success">PayPal confirmed the hold. The funds are locked in escrow.</div>}
        {search.get('cancelled') && <div role="status" className="rounded-md border border-warning bg-warning-container p-3 text-body-sm text-warning">You left PayPal without approving. Nothing was held; you can try again.</div>}
        {search.get('error') && <ErrorBanner error={{ message: search.get('error') }} />}
        {job.error && !finished && <ErrorBanner error={{ message: job.error }} />}

        <Card title="Settlement lifecycle"><StateStepper state={job.state} /></Card>
        <Brief job={job} />
        {job.verdict && <Verdict job={job} />}
        <Deliverable job={job} />
        <Card title="Money timeline"><MoneyTimeline events={events} /></Card>
      </Pane>
      {/* Right column: the money and what you can do next. On phones it comes first; on desktop it stays in view. */}
      <Pane className="order-first space-y-6 lg:order-none">
        <MoneyCard job={job} />
        <ActionPanel job={job} acting={acting} health={health} onChanged={refresh} />
        <PayPalIds job={job} />
      </Pane>
    </Panes>
  )
}
