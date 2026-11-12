// Mirrors the backend state machine (agentescrow/domain/state_machine.py).

/** Display metadata for every job state. `tone` maps to the status color pairs in DESIGN.md. */
export const STATE_META = {
  POSTED: { label: 'Posted', tone: 'neutral', hint: 'Waiting for a worker to accept' },
  ACCEPTED: { label: 'Accepted', tone: 'info', hint: 'A worker committed; the buyer must fund the escrow' },
  FUNDS_PENDING: { label: 'Awaiting approval', tone: 'warning', hint: 'The buyer must approve the PayPal hold' },
  ESCROW_LOCKED: { label: 'Escrow locked', tone: 'held', hint: 'Funds are held; the worker may start' },
  SUBMITTED: { label: 'Submitted', tone: 'info', hint: 'The worker delivered; arbitration is next' },
  ARBITRATING: { label: 'Arbitrating', tone: 'info', hint: 'The arbiter is checking the work' },
  NEEDS_REVIEW: { label: 'Needs review', tone: 'warning', hint: 'Arbitration could not finish; it can be retried' },
  SETTLING: { label: 'Settling', tone: 'info', hint: 'Moving money through PayPal' },
  SETTLED: { label: 'Settled', tone: 'success', hint: 'Captured and the worker was paid' },
  VOIDED: { label: 'Voided', tone: 'danger', hint: 'The hold was released; the buyer was not charged' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral', hint: 'Closed before any money was locked' },
}

export const TERMINAL_STATES = ['SETTLED', 'VOIDED', 'CANCELLED']

/** The happy-path steps shown in the stepper (the last step is Settled, Voided or Cancelled). */
export const STEPS = [
  { key: 'POSTED', label: 'Posted' },
  { key: 'ACCEPTED', label: 'Accepted' },
  { key: 'FUNDS_PENDING', label: 'Funds pending' },
  { key: 'ESCROW_LOCKED', label: 'Escrow locked' },
  { key: 'SUBMITTED', label: 'Submitted' },
  { key: 'ARBITRATING', label: 'Arbitrating' },
  { key: 'SETTLING', label: 'Settling' },
  { key: 'DONE', label: 'Settled' },
]

const ORDER = STEPS.map((step) => step.key)

/** Index of the current step (NEEDS_REVIEW sits at Arbitrating; terminal states are the last step). */
export function stepIndex(state) {
  if (isTerminal(state)) return ORDER.indexOf('DONE')
  if (state === 'NEEDS_REVIEW') return ORDER.indexOf('ARBITRATING')
  const index = ORDER.indexOf(state)
  return index === -1 ? 0 : index
}

/** Label for the final step, which depends on how the job ended. */
export function finalStepLabel(state) {
  if (state === 'VOIDED') return 'Voided'
  if (state === 'CANCELLED') return 'Cancelled'
  return 'Settled'
}

export function stateMeta(state) {
  return STATE_META[state] ?? { label: state, tone: 'neutral', hint: '' }
}

export function isTerminal(state) {
  return TERMINAL_STATES.includes(state)
}
