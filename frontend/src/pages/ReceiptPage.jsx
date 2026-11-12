import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import * as api from '../api/client.js'
import CodeBlock from '../components/CodeBlock.jsx'
import Icon from '../components/Icon.jsx'
import { Button, Card, EmptyState, ErrorBanner, MonoId, Page, Spinner } from '../components/ui.jsx'
import { useAsyncAction } from '../hooks/useAsync.js'
import { formatScore, formatUsd } from '../lib/format.js'
import { sha256Hex } from '../lib/hash.js'

const HEADLINES = {
  FULL: { title: 'Paid in full', tone: 'text-success' },
  PARTIAL: { title: 'Partially paid', tone: 'text-held' },
  VOID: { title: 'Voided: buyer charged $0.00', tone: 'text-danger' },
}

function Row({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 text-body-md last:border-0">
      <dt className="text-text-muted">{label}</dt>
      <dd className="tabular text-right font-semibold">{children}</dd>
    </div>
  )
}

function Verdict({ ok, children }) {
  return (
    <p role="status" className={`flex items-start gap-2 rounded-md p-3 text-body-sm font-semibold ${ok ? 'bg-success-container text-success' : 'bg-danger-container text-danger'}`}>
      <Icon name={ok ? 'check' : 'x'} className="mt-0.5 h-4 w-4 shrink-0" /> <span>{children}</span>
    </p>
  )
}

/** Verify the signature, and audit the hidden tests against the commitment, without trusting this page. */
function Audit({ data, jobId }) {
  const [signature, setSignature] = useState(null)
  const [revealed, setRevealed] = useState(null)
  const [browserHash, setBrowserHash] = useState('')
  const [verify, verifyState] = useAsyncAction(async () => setSignature(await api.verifyReceipt(data)))
  const [reveal, revealState] = useAsyncAction(async () => {
    const result = await api.getHiddenTests(jobId)
    setRevealed(result)
    setBrowserHash(await sha256Hex(result.tests))
  })
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = Object.assign(document.createElement('a'), { href: url, download: `receipt-${jobId}.json` })
    link.click()
    URL.revokeObjectURL(url)
  }
  const commitment = data.receipt.hidden_tests_sha256

  return (
    <Card title="Audit this verdict" className="no-print">
      <div className="space-y-4">
        <p className="text-body-sm text-text-muted">
          The receipt is signed with the platform's Ed25519 key (key id <code className="font-mono text-mono">{data.key_id}</code>). Anyone can verify it offline with <code className="font-mono text-mono">scripts/verify_receipt.py</code>.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" busy={verifyState.busy} onClick={verify}>Verify signature</Button>
          <Button variant="secondary" onClick={download}>Download receipt (JSON)</Button>
          <Button variant="secondary" busy={revealState.busy} onClick={reveal}>Reveal hidden tests</Button>
        </div>
        <ErrorBanner error={verifyState.error ?? revealState.error} />
        {signature && <Verdict ok={signature.valid}>{signature.valid ? 'The signature is valid: this receipt is exactly what the platform issued.' : 'The signature does NOT match: this receipt was altered.'}</Verdict>}
        {revealed && (
          <div className="space-y-3">
            <Verdict ok={revealed.matches_commitment && (!browserHash || browserHash === commitment)}>
              {revealed.matches_commitment
                ? `These are the tests that were committed to before the work started${browserHash ? ' (your browser recomputed the SHA-256 and it matches)' : ''}.`
                : 'These tests do NOT match the commitment.'}
            </Verdict>
            <CodeBlock code={revealed.tests} label="Revealed hidden tests" />
          </div>
        )}
      </div>
    </Card>
  )
}

export default function ReceiptPage() {
  const { jobId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.getReceipt(jobId).then(setData).catch(setError)
  }, [jobId])

  if (error?.status === 409) {
    return (
      <Page>
        <EmptyState icon="clock" title="No receipt yet" action={<Link className="font-semibold text-tertiary underline" to={`/jobs/${jobId}`}>Back to the job</Link>}>
          A receipt exists once the job is settled or voided.
        </EmptyState>
      </Page>
    )
  }
  if (error) return <Page><ErrorBanner error={error} /></Page>
  if (!data) return <Page><p className="flex items-center gap-2 text-text-muted"><Spinner /> Loading receipt…</p></Page>

  const { receipt, signature } = data
  const headline = HEADLINES[receipt.outcome] ?? HEADLINES.VOID
  const sandbox = receipt.tiers?.sandbox

  return (
    <Page narrow="max-w-2xl" className="space-y-6">
      {/* Static action bar: stays under the header while the receipt scrolls. */}
      <div className="no-print sticky top-0 z-10 -mx-4 flex items-center justify-between gap-3 border-b border-border bg-neutral/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6">
        <Link className="inline-flex min-h-11 items-center text-body-sm font-semibold text-tertiary underline" to={`/jobs/${jobId}`}>← Back to the job</Link>
        <Button variant="secondary" onClick={() => window.print()}><Icon name="print" /> Print receipt</Button>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="bg-tertiary-container px-6 py-5">
          <p className="flex items-center gap-2 text-label-caps font-semibold uppercase tracking-label-caps text-tertiary"><Icon name="shield" /> AgentEscrow verdict receipt</p>
          <h1 className={`mt-1 text-h1 font-bold ${headline.tone}`}>{headline.title}</h1>
          <p className="break-words text-body-md">{receipt.title} · <span className="font-mono text-mono">{receipt.job_id}</span></p>
        </div>
        <div className="space-y-6 p-6">
          {receipt.simulated && <p className="rounded-md bg-warning-container p-3 text-body-sm font-semibold text-warning">Simulated: no real PayPal calls were made and no money moved.</p>}
          <p className="text-body-md">{receipt.reason}</p>
          <dl>
            <Row label="Bounty">{formatUsd(receipt.bounty_usd)}</Row>
            <Row label="Buyer charged">{formatUsd(receipt.buyer_charged_usd)}</Row>
            <Row label="Worker paid">{formatUsd(receipt.worker_payout_usd)}</Row>
            <Row label="Platform fee">{formatUsd(receipt.platform_fee_usd)}</Row>
            <Row label="Verification score">{formatScore(receipt.v_score)}</Row>
            {sandbox && <Row label="Hidden tests">{sandbox.passed} of {sandbox.total} passed</Row>}
            <Row label="Integrity gate">{receipt.tiers?.integrity.ok ? 'Passed' : 'Failed'}</Row>
          </dl>

          <div className="space-y-3 text-body-sm">
            <h2 className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">References</h2>
            {Object.entries({ 'PayPal order': receipt.paypal.order_id, Authorization: receipt.paypal.authorization_id, Capture: receipt.paypal.capture_id, 'Payout batch': receipt.paypal.payout_batch_id, 'Deliverable SHA-256': receipt.deliverable_sha256, 'Hidden tests SHA-256 (committed at posting)': receipt.hidden_tests_sha256 })
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-text-muted">{label}</span>
                  <MonoId value={value} label={label} />
                </div>
              ))}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
              <span className="text-text-muted">Signature ({data.alg})</span>
              <MonoId value={signature} label="signature" />
            </div>
          </div>
        </div>
      </Card>

      <Audit data={data} jobId={jobId} />
    </Page>
  )
}
