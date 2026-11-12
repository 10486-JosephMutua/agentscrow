import { formatScore } from '../lib/format.js'

const CX = 100
const CY = 100
const R = 80

/** Point on the semicircle for a value in [0, 1] (0 = far left, 1 = far right). */
function pointAt(value, radius = R) {
  const angle = Math.PI * (1 - Math.min(Math.max(value, 0), 1))
  return [CX + radius * Math.cos(angle), CY - radius * Math.sin(angle)]
}

/** A 0 to 1 gauge with markers at the partial (0.50) and full (0.85) payment thresholds. */
export default function ScoreGauge({ value, label = 'Verification score' }) {
  const [endX, endY] = pointAt(value)
  const arc = (from, to) => {
    const [x1, y1] = pointAt(from)
    const [x2, y2] = pointAt(to)
    return `M ${x1} ${y1} A ${R} ${R} 0 0 1 ${x2} ${y2}`
  }
  const color = value >= 0.85 ? 'var(--color-success)' : value >= 0.5 ? 'var(--color-held)' : 'var(--color-danger)'
  return (
    <figure className="m-0 text-center" aria-label={`${label}: ${formatScore(value)}`}>
      <svg viewBox="0 -16 200 136" className="mx-auto w-full max-w-64" role="img" aria-hidden="true">
        <path d={arc(0, 1)} fill="none" stroke="var(--color-surface-muted)" strokeWidth="14" strokeLinecap="round" />
        {value > 0 && <path d={arc(0, Math.max(value, 0.001))} fill="none" stroke={color} strokeWidth="14" strokeLinecap="round" />}
        {[0.5, 0.85].map((mark) => {
          const [x1, y1] = pointAt(mark, R - 12)
          const [x2, y2] = pointAt(mark, R + 12)
          const [tx, ty] = pointAt(mark, R + 22)
          return (
            <g key={mark}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--color-primary)" strokeWidth="2" />
              <text x={tx} y={ty} fontSize="9" textAnchor="middle" fill="var(--color-text-muted)">
                {mark.toFixed(2)}
              </text>
            </g>
          )
        })}
        <circle cx={endX} cy={endY} r="4" fill="var(--color-primary)" />
        <text x={CX} y="92" textAnchor="middle" fontSize="28" fontWeight="700" fill="var(--color-text)" className="tabular">
          {formatScore(value)}
        </text>
      </svg>
      <figcaption className="text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">{label}</figcaption>
    </figure>
  )
}
