import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import * as api from '../api/client.js'
import Icon from '../components/Icon.jsx'
import LintReport from '../components/LintReport.jsx'
import SitePreferencesForm, { DEFAULT_SITE, siteIsValid } from '../components/SitePreferencesForm.jsx'
import { Button, Card, ErrorBanner, Page, PageTitle, Spinner } from '../components/ui.jsx'
import { useAsyncAction } from '../hooks/useAsync.js'
import { formatUsd } from '../lib/format.js'

const DEADLINES = [
  { hours: 1, label: '1 hour' },
  { hours: 6, label: '6 hours' },
  { hours: 24, label: '1 day' },
  { hours: 72, label: '3 days' },
  { hours: 168, label: '7 days' },
]
const INPUT = 'min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-body-md'
const CODE = `${INPUT} font-mono text-mono`

const EXAMPLE = {
  title: 'Double a number',
  description: 'Implement double(x) returning twice the integer x. Negative numbers and zero must work too.',
  function_name: 'double',
  function_signature: 'def double(x: int) -> int',
  public_tests: 'from solution import double\n\n\ndef test_two():\n    assert double(2) == 4\n',
  hidden_tests:
    'from solution import double\n\n\ndef test_zero():\n    assert double(0) == 0\n\n\ndef test_negative():\n    assert double(-3) == -6\n\n\ndef test_large():\n    assert double(10**6) == 2 * 10**6\n\n\ndef test_one():\n    assert double(1) == 2\n',
  reference_solution: 'def double(x: int) -> int:\n    return x * 2\n',
}
const EMPTY = Object.fromEntries(Object.keys(EXAMPLE).map((key) => [key, '']))

function TemplatePicker({ templates, value, onChange }) {
  return (
    <fieldset>
      <legend className="mb-2 text-body-sm font-semibold">What should the worker build?</legend>
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Task template">
        {[
          ...templates,
          { id: 'site', title: 'A website from your preferences', summary: 'Pick sections, colours and a contact form. Every preference becomes a check on the delivered site.', signature: '' },
          { id: 'custom', title: 'Your own task', summary: 'Write the description, tests and a reference solution. We check it in the sandbox first.', signature: '' },
        ].map((item) => (
          <label key={item.id} className={`cursor-pointer rounded-lg border p-4 ${value === item.id ? 'border-tertiary bg-tertiary-container' : 'border-border bg-surface hover:bg-surface-muted'}`}>
            <input type="radio" name="template" className="sr-only" checked={value === item.id} onChange={() => onChange(item.id)} />
            <span className="flex items-center gap-2 text-h3 font-semibold">
              {item.id === 'custom' && <Icon name="code" />}
              {item.id === 'site' && <Icon name="doc" />} {item.title}
            </span>
            <span className="mt-1 block text-body-sm text-text-muted">{item.summary}</span>
            {item.signature && <code className="mt-2 block font-mono text-mono">{item.signature}</code>}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function CustomTaskForm({ task, onChange, report, onValidate, validating, ticket, error }) {
  const set = (key) => (event) => onChange({ ...task, [key]: event.target.value })
  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-h3 font-semibold">Define your task</h2>
        <Button variant="secondary" type="button" onClick={() => onChange(EXAMPLE)}>Load an example</Button>
      </div>
      <div>
        <label htmlFor="t-title" className="mb-1 block text-body-sm font-semibold">Title</label>
        <input id="t-title" className={INPUT} value={task.title} onChange={set('title')} maxLength={80} />
      </div>
      <div>
        <label htmlFor="t-desc" className="mb-1 block text-body-sm font-semibold">Description the worker will read</label>
        <textarea id="t-desc" className={INPUT} rows={3} value={task.description} onChange={set('description')} maxLength={2000} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="t-fn" className="mb-1 block text-body-sm font-semibold">Function name</label>
          <input id="t-fn" className={CODE} value={task.function_name} onChange={set('function_name')} spellCheck={false} />
        </div>
        <div>
          <label htmlFor="t-sig" className="mb-1 block text-body-sm font-semibold">Signature</label>
          <input id="t-sig" className={CODE} value={task.function_signature} onChange={set('function_signature')} spellCheck={false} />
        </div>
      </div>
      <div>
        <label htmlFor="t-pub" className="mb-1 block text-body-sm font-semibold">Public example tests (the worker sees these)</label>
        <textarea id="t-pub" className={CODE} rows={5} value={task.public_tests} onChange={set('public_tests')} spellCheck={false} />
      </div>
      <div>
        <label htmlFor="t-hid" className="mb-1 block text-body-sm font-semibold">Hidden tests (kept secret, committed by hash, published after the verdict)</label>
        <textarea id="t-hid" className={CODE} rows={8} value={task.hidden_tests} onChange={set('hidden_tests')} spellCheck={false} />
      </div>
      <div>
        <label htmlFor="t-ref" className="mb-1 block text-body-sm font-semibold">Reference solution (never shown to anyone; proves your tests are fair)</label>
        <textarea id="t-ref" className={CODE} rows={5} value={task.reference_solution} onChange={set('reference_solution')} spellCheck={false} />
      </div>
      <Button type="button" variant="secondary" busy={validating} onClick={onValidate} className="w-full">
        Check the task in the sandbox
      </Button>
      <ErrorBanner error={error} />
      <LintReport checks={report?.checks} />
      {ticket && <p className="flex items-center gap-2 text-body-sm font-semibold text-success"><Icon name="check" /> The task passed every check. You can post it.</p>}
    </div>
  )
}

export default function CreateJobPage() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState(null)
  const [template, setTemplate] = useState('rle')
  const [bounty, setBounty] = useState('5.00')
  const [hours, setHours] = useState(24)
  const [task, setTask] = useState(EMPTY)
  const [report, setReport] = useState(null)
  const [ticket, setTicket] = useState(null)
  const [site, setSite] = useState(DEFAULT_SITE)
  const amount = Number(bounty)
  const valid = Number.isFinite(amount) && amount >= 1 && amount <= 100
  const custom = template === 'custom'
  const website = template === 'site'

  useEffect(() => {
    api.getTemplates().then(setTemplates).catch(() => setTemplates([]))
  }, [])

  const edit = (next) => {
    setTask(next)
    setTicket(null) // any change invalidates an earlier check
    setReport(null)
  }

  const [validate, validation] = useAsyncAction(async () => {
    const result = await api.validateTask(task)
    setReport(result)
    setTicket(result.ok ? result.ticket : null)
  })

  const [create, { busy, error, clearError }] = useAsyncAction(async () => {
    const options = { bountyUsd: amount.toFixed(2), deadlineHours: hours }
    const job = await api.createJob(website ? { ...options, site } : custom ? { ...options, task, validationTicket: ticket } : { ...options, template })
    navigate(`/jobs/${job.job_id}`)
  })

  if (templates === null) return <Page><p className="flex items-center gap-2 text-text-muted"><Spinner /> Loading…</p></Page>

  return (
    <Page narrow="max-w-2xl">
      <p className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">Programmatic work order</p>
      <PageTitle title="Post a job" subtitle="Describe the work, set the bounty, and let escrow protect both sides." />
      <Card>
        <form
          className="space-y-6"
          onSubmit={(event) => {
            event.preventDefault()
            if (valid && (!custom || ticket) && (!website || siteIsValid(site))) create()
          }}
        >
          <TemplatePicker templates={templates} value={template} onChange={setTemplate} />
          {custom && <CustomTaskForm task={task} onChange={edit} report={report} onValidate={validate} validating={validation.busy} ticket={ticket} error={validation.error} />}
          {website && <SitePreferencesForm value={site} onChange={setSite} />}
          {website && <p className="rounded-md bg-surface-muted p-3 text-body-sm text-text-muted">Your preferences are compiled into checks by fixed rules (no AI), committed by hash before any money is locked, and run against the delivered page. Only the tone is scored by the AI judge.</p>}
          {!custom && !website && <p className="rounded-md bg-surface-muted p-3 text-body-sm text-text-muted">Hidden tests are generated fresh for every job (fixed edge cases plus random ones), so no worker can memorize them.</p>}

          <div>
            <label htmlFor="bounty" className="mb-1 block text-body-sm font-semibold">Bounty (USD)</label>
            <input id="bounty" type="number" inputMode="decimal" min="1" max="100" step="0.5" value={bounty} onChange={(event) => setBounty(event.target.value)} className={`${INPUT} tabular`} aria-describedby="bounty-help" />
            <p id="bounty-help" className={`mt-1 text-body-sm ${valid ? 'text-text-muted' : 'text-danger'}`}>
              {valid ? 'Between $1 and $100 in this sandbox demo.' : 'Enter an amount between $1.00 and $100.00.'}
            </p>
          </div>

          <div>
            <label htmlFor="deadline" className="mb-1 block text-body-sm font-semibold">Deadline for delivery</label>
            <select id="deadline" value={hours} onChange={(event) => setHours(Number(event.target.value))} className={INPUT}>
              {DEADLINES.map((item) => (
                <option key={item.hours} value={item.hours}>{item.label}</option>
              ))}
            </select>
            <p className="mt-1 text-body-sm text-text-muted">If nothing is delivered by then, the hold is released and you pay nothing.</p>
          </div>

          <div className="flex gap-3 rounded-md border border-tertiary bg-tertiary-container p-4 text-body-sm text-tertiary">
            <Icon name="shield" className="mt-0.5 h-5 w-5 shrink-0" />
            <p>
              A signed spending mandate caps this escrow at <b className="tabular">{formatUsd(valid ? amount : 0)}</b>. The payment server will refuse anything above it, whatever any agent asks for.
            </p>
          </div>

          {/* Stays in view at the bottom of the screen while the long form scrolls behind it. */}
          <div className="sticky bottom-0 -mx-6 -mb-6 space-y-2 rounded-b-lg border-t border-border bg-surface/95 px-6 py-4 backdrop-blur">
            <ErrorBanner error={error} onDismiss={clearError} />
            <Button type="submit" variant="accent" busy={busy} disabled={!valid || (custom && !ticket) || (website && !siteIsValid(site))} className="w-full">
              {custom && !ticket ? 'Check the task first' : website && !siteIsValid(site) ? 'Fill in the business name, purpose and a section' : 'Post job'}
            </Button>
          </div>
        </form>
      </Card>
    </Page>
  )
}
