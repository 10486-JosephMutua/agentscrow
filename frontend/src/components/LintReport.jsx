import Icon from './Icon.jsx'

/** The sandbox lint of a custom task: one row per check, with the reason when it failed. */
export default function LintReport({ checks }) {
  if (!checks?.length) return null
  return (
    <ul className="space-y-2" aria-label="Task checks">
      {checks.map((check) => (
        <li key={check.name} className={`flex items-start gap-2 rounded-md p-2 text-body-sm ${check.passed ? 'bg-success-container text-success' : 'bg-danger-container text-danger'}`}>
          <Icon name={check.passed ? 'check' : 'x'} className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            <span className="font-semibold">{check.name}</span>
            {check.detail && <span className="block opacity-90">{check.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}
