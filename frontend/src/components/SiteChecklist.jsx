import Icon from './Icon.jsx'

function Group({ title, items }) {
  if (!items.length) return null
  const met = items.filter((item) => item.passed).length
  return (
    <div className="space-y-2">
      <h4 className="flex items-center justify-between text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">
        <span>{title}</span>
        <span className="tabular normal-case tracking-normal">{met} of {items.length} met</span>
      </h4>
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id} className={`flex items-start gap-2 rounded-md p-2 text-body-sm ${item.passed ? 'bg-success-container text-success' : 'bg-danger-container text-danger'}`} data-testid={`check-${item.id}`}>
            <Icon name={item.passed ? 'check' : 'x'} className="mt-0.5 h-4 w-4 shrink-0" title={item.passed ? 'Met' : 'Not met'} />
            <span>
              <span className="font-semibold">{item.label}</span>
              {item.detail && <span className="block opacity-90">{item.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** "Did it fulfil what the buyer asked for?" One line per preference, with the reason each one passed or failed. */
export default function SiteChecklist({ items }) {
  if (!items?.length) return null
  const preferences = items.filter((item) => item.source === 'preference')
  const baseline = items.filter((item) => item.source !== 'preference')
  const met = items.filter((item) => item.passed).length
  return (
    <div className="space-y-4" aria-label="Preference checklist">
      <p className="text-body-md font-semibold">
        {met === items.length ? 'Every preference was met.' : `${met} of ${items.length} checks were met.`}
      </p>
      <Group title="What the buyer asked for" items={preferences} />
      <Group title="Quality bar for every site" items={baseline} />
    </div>
  )
}
