import { useState } from 'react'
import * as api from '../api/client.js'
import { useAsyncAction } from '../hooks/useAsync.js'
import { isTerminal } from '../lib/states.js'
import { Button, ButtonLink, Card, ErrorBanner, Spinner } from './ui.jsx'

const PERSONAS = [
  { value: 'honest', label: 'Honest worker', hint: 'Solves the task correctly' },
  { value: 'sloppy', label: 'Sloppy worker', hint: 'Misses runs longer than nine characters' },
  { value: 'cheater', label: 'Cheating worker', hint: 'Tries to sway the judge (a red-team test of the arbiter)' },
]

const INPUT = 'w-full rounded-md border border-border bg-surface px-3 py-2 text-body-md'

function Note({ children }) {
  return <p className="text-body-sm text-text-muted">{children}</p>
}

function Working({ children }) {
  return (
    <p className="flex items-center gap-2 text-body-md">
      <Spinner /> {children}
    </p>
  )
}

/** Run a worker agent (or a scripted persona) against a funded job, then arbitrate and settle. */
function PersonaRunner({ job, health, onChanged }) {
  const [persona, setPersona] = useState('honest')
  const [run, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.runJob(job.job_id, persona)
    await onChanged()
  })
  const scripted = health?.worker_mode === 'scripted'
  const website = Boolean(job.contract.specification.preferences)
  const hint = (item) =>
    website
      ? { honest: 'Builds a website that meets every preference', sloppy: 'Forgets the contact form and image alt text, and picks the wrong accent colour', cheater: 'Delivers a placeholder with a remote script and a note to the judge (a red-team test of the arbiter)' }[item.value]
      : item.hint
  return (
    <div className="space-y-3">
      <label className="block text-body-sm font-semibold" htmlFor="persona">
        Which worker agent should take this job?
      </label>
      <select id="persona" value={persona} onChange={(event) => setPersona(event.target.value)} className={INPUT}>
        {PERSONAS.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      <Note>{hint(PERSONAS.find((item) => item.value === persona))}.</Note>
      <Note>{scripted ? 'Scripted personas (no LLM) keep demos repeatable.' : `A Groq-powered worker agent will write and test the ${website ? 'website' : 'code'}, using this persona as its brief.`}</Note>
      <Button variant="accent" busy={busy} onClick={run} className="w-full">
        Run worker agent
      </Button>
      <ErrorBanner error={error} onDismiss={clearError} />
    </div>
  )
}

/** For an external worker: submit your own solution instead of running an agent. */
function SubmitForm({ job, onChanged }) {
  const spec = job.contract.specification
  const website = Boolean(spec.preferences)
  const [code, setCode] = useState(website ? '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title></title>\n  <style></style>\n</head>\n<body>\n</body>\n</html>\n' : `${spec.function_signature}:\n    ...\n`)
  const [explanation, setExplanation] = useState('')
  const [submit, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.submitDeliverable(job.job_id, website ? { index_html: code, explanation } : { solution_code: code, explanation })
    await api.arbitrateJob(job.job_id)
    await onChanged()
  })
  return (
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer text-body-sm font-semibold">Or submit your own solution</summary>
      <div className="mt-3 space-y-3">
        <label className="block text-body-sm font-semibold" htmlFor="solution">
          {website ? 'index.html' : 'solution.py'}
        </label>
        <textarea id="solution" value={code} onChange={(event) => setCode(event.target.value)} rows={8} spellCheck={false} className={`${INPUT} font-mono text-mono`} />
        <label className="block text-body-sm font-semibold" htmlFor="explanation">
          Explanation (at least 20 characters)
        </label>
        <textarea id="explanation" value={explanation} onChange={(event) => setExplanation(event.target.value)} rows={3} className={INPUT} />
        <Button busy={busy} onClick={submit} disabled={code.length < (website ? 100 : 20) || explanation.length < 20} className="w-full">
          Submit for arbitration
        </Button>
        <ErrorBanner error={error} onDismiss={clearError} />
      </div>
    </details>
  )
}

function AcceptForm({ job, onChanged, defaults = {} }) {
  const [workerId, setWorkerId] = useState(defaults.workerId ?? '')
  const [email, setEmail] = useState(defaults.email ?? '')
  const [accept, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.acceptJob(job.job_id, { workerId, workerEmail: email })
    await onChanged()
  })
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        accept()
      }}
    >
      <label className="block text-body-sm font-semibold" htmlFor="worker-id">
        Your worker name
      </label>
      <input id="worker-id" required value={workerId} onChange={(event) => setWorkerId(event.target.value)} className={INPUT} placeholder="e.g. codesmith-agent" />
      <label className="block text-body-sm font-semibold" htmlFor="worker-email">
        PayPal email for the payout
      </label>
      <input id="worker-email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} className={INPUT} placeholder="payouts-simulator-receiver@paypal.com" />
      <Note>In the sandbox, use PayPal's test receiver shown above, or any sandbox personal account.</Note>
      <Button type="submit" variant="accent" busy={busy} className="w-full">
        Accept this job
      </Button>
      <ErrorBanner error={error} onDismiss={clearError} />
    </form>
  )
}

function RetryButton({ job, label, onChanged }) {
  const [retry, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.arbitrateJob(job.job_id)
    await onChanged()
  })
  return (
    <div className="space-y-3">
      <Button busy={busy} onClick={retry} className="w-full">
        {label}
      </Button>
      <ErrorBanner error={error} onDismiss={clearError} />
    </div>
  )
}

function CancelButton({ job, label, onChanged }) {
  const [cancel, { busy, error, clearError }] = useAsyncAction(async () => {
    await api.cancelJob(job.job_id)
    await onChanged()
  })
  return (
    <div className="space-y-3">
      <Button variant="danger" busy={busy} onClick={cancel} className="w-full">
        {label}
      </Button>
      <ErrorBanner error={error} onDismiss={clearError} />
    </div>
  )
}

function ReleaseButton({ job, label, action, onChanged }) {
  const [release, { busy, error, clearError }] = useAsyncAction(async () => {
    await action(job.job_id)
    await onChanged()
  })
  return (
    <div className="space-y-3">
      <Button variant="secondary" busy={busy} onClick={release} className="w-full">
        {label}
      </Button>
      <ErrorBanner error={error} onDismiss={clearError} />
    </div>
  )
}

function BuyerSteps({ job, health, onChanged }) {
  const simulated = health?.paypal_mode === 'simulated'
  const [open, openState] = useAsyncAction(async () => {
    await api.openEscrow(job.job_id)
    await onChanged()
  })
  const [confirm, confirmState] = useAsyncAction(async () => {
    await api.confirmFunding(job.job_id)
    await onChanged()
  })

  switch (job.state) {
    case 'POSTED':
      return (
        <>
          <Note>Waiting for a worker to accept this job. You can cancel at any time before funding.</Note>
          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-body-sm font-semibold">No other worker? Take the job yourself (demo)</summary>
            <div className="mt-3">
              <AcceptForm job={job} onChanged={onChanged} defaults={{ workerId: 'demo-worker', email: 'payouts-simulator-receiver@paypal.com' }} />
            </div>
          </details>
          <CancelButton job={job} label="Cancel job" onChanged={onChanged} />
        </>
      )
    case 'ACCEPTED':
      return (
        <>
          <Note>
            {health?.buyer_mode === 'agent' ? 'A Groq-powered buyer agent will open the escrow with your signed spending cap.' : 'The escrow will be opened with your signed spending cap.'} Nothing is charged yet: PayPal only holds the funds.
          </Note>
          <Button variant="accent" busy={openState.busy} onClick={open} className="w-full">
            Open escrow
          </Button>
          <ErrorBanner error={openState.error} onDismiss={openState.clearError} />
          <ReleaseButton job={job} label={`Reject ${job.worker_id ?? 'this worker'} and reopen the job`} action={api.rejectWorker} onChanged={onChanged} />
          <CancelButton job={job} label="Cancel job" onChanged={onChanged} />
        </>
      )
    case 'FUNDS_PENDING':
      return (
        <>
          <Note>{simulated ? 'Simulation: approving is instant and moves no money.' : 'You will be sent to PayPal to approve a hold. Nothing is charged until the work is verified.'}</Note>
          {job.approve_url && (
            <ButtonLink variant="accent" href={job.approve_url} className="w-full">
              Approve the hold in PayPal
            </ButtonLink>
          )}
          <Button variant="secondary" busy={confirmState.busy} onClick={confirm} className="w-full">
            I have approved: check now
          </Button>
          <ErrorBanner error={confirmState.error} onDismiss={confirmState.clearError} />
        </>
      )
    case 'ESCROW_LOCKED':
      return (
        <>
          <PersonaRunner job={job} health={health} onChanged={onChanged} />
          <CancelButton job={job} label="Cancel and release the hold" onChanged={onChanged} />
        </>
      )
    case 'SUBMITTED':
      return <RetryButton job={job} label="Run arbitration" onChanged={onChanged} />
    case 'NEEDS_REVIEW':
      return (
        <>
          <Note>Arbitration could not finish because of an infrastructure problem. Nobody has been paid or penalised; retry when ready.</Note>
          <RetryButton job={job} label="Retry arbitration" onChanged={onChanged} />
        </>
      )
    case 'ARBITRATING':
      return <Working>The arbiter is checking the work…</Working>
    case 'SETTLING':
      return job.error ? (
        <>
          <Note>A PayPal step failed. The decision is saved and settlement can safely resume without double-charging.</Note>
          <RetryButton job={job} label="Resume settlement" onChanged={onChanged} />
        </>
      ) : (
        <Working>Moving money through PayPal…</Working>
      )
    default:
      return null
  }
}

function WorkerSteps({ job, health, onChanged }) {
  switch (job.state) {
    case 'ACCEPTED':
      return (
        <>
          <Note>Waiting for the buyer to lock the funds. You only start work once PayPal confirms the money is held.</Note>
          <ReleaseButton job={job} label="Withdraw from this job" action={api.withdraw} onChanged={onChanged} />
        </>
      )
    case 'FUNDS_PENDING':
      return <Note>The buyer is approving the PayPal hold. You only start work once PayPal confirms the money is held.</Note>
    case 'ESCROW_LOCKED':
      return (
        <>
          <PersonaRunner job={job} health={health} onChanged={onChanged} />
          <SubmitForm job={job} onChanged={onChanged} />
        </>
      )
    case 'SUBMITTED':
      return <RetryButton job={job} label="Run arbitration" onChanged={onChanged} />
    case 'NEEDS_REVIEW':
      return <RetryButton job={job} label="Retry arbitration" onChanged={onChanged} />
    case 'ARBITRATING':
      return <Working>The arbiter is checking your work…</Working>
    case 'SETTLING':
      return <Working>Moving money through PayPal…</Working>
    default:
      return <Note>Waiting for the buyer.</Note>
  }
}

/** The "what can I do next?" card. What it shows depends on who you are (`acting`) and the job state. */
export default function ActionPanel({ job, acting, health, onChanged }) {
  let body
  if (isTerminal(job.state)) {
    body =
      job.state === 'CANCELLED' ? (
        <Note>This job was closed before any money was locked.</Note>
      ) : (
        <ButtonLink variant="accent" to={`/jobs/${job.job_id}/receipt`} className="w-full">
          View the verdict receipt
        </ButtonLink>
      )
  } else if (acting === 'buyer' || acting === 'admin') {
    body = <BuyerSteps job={job} health={health} onChanged={onChanged} />
  } else if (acting === 'worker') {
    body = <WorkerSteps job={job} health={health} onChanged={onChanged} />
  } else if (job.state === 'POSTED') {
    body = <AcceptForm job={job} onChanged={onChanged} />
  } else {
    body = <Note>You are viewing this job as a guest. Only its buyer and worker can act on it.</Note>
  }
  return (
    <Card title={acting === 'admin' ? 'Operator actions' : 'Next step'}>
      <div className="space-y-4">{body}</div>
    </Card>
  )
}
