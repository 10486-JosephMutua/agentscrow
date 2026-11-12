import { formatScore } from '../lib/format.js'
import Icon from './Icon.jsx'
import { Chip } from './ui.jsx'

function TierCard({ title, weight, status, score, children }) {
  const styles = {
    pass: { tone: 'success', icon: 'check', text: 'Passed' },
    fail: { tone: 'danger', icon: 'x', text: 'Failed' },
    skipped: { tone: 'neutral', icon: 'dot', text: 'Not run' },
  }[status]
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4" data-testid={`tier-${title}`}>
      <div>
        <h3 className="text-h3 font-semibold">{title}</h3>
        <p className="text-body-sm text-text-muted">weight {weight}</p>
      </div>
      <Chip tone={styles.tone} icon={styles.icon} className="self-start">
        {styles.text}
      </Chip>
      <p className="tabular text-h1 font-bold">{score === null ? '–' : formatScore(score)}</p>
      <div className="text-body-sm text-text-muted">{children}</div>
    </div>
  )
}

/** The three arbitration tiers plus the integrity gate, from a verdict. */
export default function TierCards({ verdict }) {
  const { schema_check: schema, integrity, sandbox, semantic, tiers_skipped: skipped = [] } = verdict
  const sandboxStatus = !sandbox || skipped.includes('sandbox') ? 'skipped' : sandbox.failed === 0 && sandbox.total > 0 ? 'pass' : 'fail'
  const website = sandbox?.backend === 'html-checks'
  const semanticStatus = !semantic ? 'skipped' : semantic.manipulation_suspected ? 'fail' : semantic.score >= 0.5 ? 'pass' : 'fail'

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <TierCard title="Schema" weight="30%" status={schema.valid ? 'pass' : 'fail'} score={schema.score}>
          {schema.valid ? 'Deliverable matches the contract schema.' : (schema.errors ?? []).slice(0, 3).join(' · ') || 'Schema mismatch.'}
        </TierCard>
        <TierCard title={website ? 'Preference checks' : 'Hidden tests'} weight="40%" status={sandboxStatus} score={sandbox && sandboxStatus !== 'skipped' ? sandbox.score : null}>
          {sandboxStatus === 'skipped'
            ? 'The code was never executed.'
            : website
              ? `${sandbox.passed} of ${sandbox.total} preference checks were met.`
              : `${sandbox.passed} of ${sandbox.total} hidden tests passed${sandbox.timed_out ? ' (timed out)' : ''} in the ${sandbox.backend} sandbox.`}
        </TierCard>
        <TierCard title={website ? 'Tone judge' : 'Semantic judge'} weight="30%" status={semanticStatus} score={semantic ? semantic.score : null}>
          {semantic ? semantic.rationale : 'Skipped: an earlier gate already decided the outcome.'}
        </TierCard>
      </div>
      <div
        className={`flex items-start gap-3 rounded-md border p-3 text-body-sm ${integrity.ok ? 'border-success bg-success-container text-success' : 'border-danger bg-danger-container text-danger'}`}
        data-testid="integrity-strip"
      >
        <Icon name={integrity.ok ? 'shield' : 'alert'} className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p className="font-semibold">{integrity.ok ? 'Integrity gate passed' : 'Integrity gate failed: the code was never run'}</p>
          {!integrity.ok && (
            <ul className="mt-1 list-disc pl-5">
              {integrity.findings.map((finding) => (
                <li key={finding}>{finding}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
