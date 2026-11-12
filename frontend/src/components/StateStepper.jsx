import { STEPS, finalStepLabel, stepIndex } from '../lib/states.js'
import Icon from './Icon.jsx'

/** Where the job is on its journey. Horizontal on wide screens, vertical on phones. */
export default function StateStepper({ state }) {
  const current = stepIndex(state)
  const failed = state === 'VOIDED' || state === 'CANCELLED'
  const needsReview = state === 'NEEDS_REVIEW'

  return (
    <ol className="flex flex-col gap-3 md:flex-row md:items-start md:gap-0" aria-label="Job progress">
      {STEPS.map((step, index) => {
        const done = index < current || (index === current && ['SETTLED'].includes(state))
        const active = index === current
        const label = step.key === 'DONE' ? finalStepLabel(state) : step.label
        const tone = active && failed ? 'bg-danger text-on-primary' : active && needsReview ? 'bg-warning text-on-primary' : active ? 'bg-primary text-on-primary' : done ? 'bg-tertiary text-on-tertiary' : 'bg-surface-muted text-text-muted'
        return (
          <li key={step.key} className="flex items-center gap-3 md:flex-1 md:flex-col md:items-start md:gap-2" aria-current={active ? 'step' : undefined}>
            <div className="flex items-center md:w-full">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-body-sm font-semibold ${tone}`}>
                {done ? <Icon name="check" /> : active && failed ? <Icon name="x" /> : index + 1}
              </span>
              {index < STEPS.length - 1 && <span className={`ml-2 hidden h-0.5 flex-1 md:block ${index < current ? 'bg-tertiary' : 'bg-border'}`} />}
            </div>
            <span className={`text-body-sm md:text-left ${active ? 'font-semibold text-text' : 'text-text-muted'}`}>{label}</span>
          </li>
        )
      })}
    </ol>
  )
}
