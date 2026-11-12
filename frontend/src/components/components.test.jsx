import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { cheatingVerdict, makeJob, passingVerdict } from '../test/fixtures.js'
import MoneyCard from './MoneyCard.jsx'
import MoneyTimeline from './MoneyTimeline.jsx'
import OutcomeBanner from './OutcomeBanner.jsx'
import ScoreGauge from './ScoreGauge.jsx'
import StateStepper from './StateStepper.jsx'
import TierCards from './TierCards.jsx'
import JobCard from './JobCard.jsx'

describe('StateStepper', () => {
  it('marks the current step and completed ones', () => {
    render(<StateStepper state="ESCROW_LOCKED" />)
    const steps = screen.getAllByRole('listitem')
    expect(steps).toHaveLength(8)
    expect(steps[3]).toHaveAttribute('aria-current', 'step')
    expect(within(steps[3]).getByText('Escrow locked')).toBeInTheDocument()
  })
  it('shows Voided as the last step for a voided job', () => {
    render(<StateStepper state="VOIDED" />)
    expect(screen.getByText('Voided')).toBeInTheDocument()
  })
})

describe('TierCards', () => {
  it('shows a clean pass', () => {
    render(<TierCards verdict={passingVerdict} />)
    expect(within(screen.getByTestId('tier-Hidden tests')).getByText(/8 of 8 hidden tests passed/)).toBeInTheDocument()
    expect(screen.getByTestId('integrity-strip')).toHaveTextContent('Integrity gate passed')
  })
  it('shows a cheater caught before execution', () => {
    render(<TierCards verdict={cheatingVerdict} />)
    expect(screen.getByTestId('integrity-strip')).toHaveTextContent('the code was never run')
    expect(screen.getByTestId('integrity-strip')).toHaveTextContent('prompt injection')
    expect(within(screen.getByTestId('tier-Hidden tests')).getByText('Not run')).toBeInTheDocument()
    expect(within(screen.getByTestId('tier-Semantic judge')).getByText('Not run')).toBeInTheDocument()
  })
  it('shows partially failing tests as a failure', () => {
    const verdict = { ...passingVerdict, sandbox: { ...passingVerdict.sandbox, passed: 5, failed: 3, score: 0.625 } }
    render(<TierCards verdict={verdict} />)
    expect(within(screen.getByTestId('tier-Hidden tests')).getByText('Failed')).toBeInTheDocument()
  })
})

describe('ScoreGauge', () => {
  it('announces its value', () => {
    render(<ScoreGauge value={0.97} />)
    expect(screen.getByLabelText('Verification score: 0.97')).toBeInTheDocument()
  })
  it('handles zero and out-of-range values', () => {
    render(<ScoreGauge value={0} label="Zero" />)
    expect(screen.getByLabelText('Zero: 0.00')).toBeInTheDocument()
  })
})

describe('MoneyCard and OutcomeBanner', () => {
  it('shows held money for a locked job', () => {
    render(<MoneyCard job={makeJob({ state: 'ESCROW_LOCKED' })} />)
    expect(screen.getByText('Held in escrow')).toBeInTheDocument()
    expect(screen.getByTestId('money-amount')).toHaveTextContent('$5.00')
  })
  it('shows $0 and a release for a voided job', () => {
    render(<MoneyCard job={makeJob({ state: 'VOIDED', decision: { outcome: 'VOID', capture_amount: '0.00' } })} />)
    expect(screen.getByTestId('money-amount')).toHaveTextContent('$0.00')
    expect(screen.getByText(/buyer charged \$0.00/)).toBeInTheDocument()
  })
  it('splits a paid job between worker and fee', () => {
    const decision = { outcome: 'FULL', capture_amount: '5.00', worker_payout: '4.67', platform_fee: '0.33', reason: 'all passed', v_score: 0.97 }
    render(<MoneyCard job={makeJob({ state: 'SETTLED', decision })} />)
    expect(screen.getByText('$4.67')).toBeInTheDocument()
    expect(screen.getByText('$0.33')).toBeInTheDocument()
  })
  it('explains the outcome', () => {
    render(<OutcomeBanner decision={{ outcome: 'PARTIAL', reason: 'V=0.82', capture_amount: '4.10', worker_payout: '3.83', platform_fee: '0.27' }} />)
    expect(screen.getByTestId('outcome-banner')).toHaveTextContent('Partially paid')
    expect(screen.getByTestId('outcome-banner')).toHaveTextContent('V=0.82')
  })
})

describe('MoneyTimeline', () => {
  it('renders events in order, and an empty state', () => {
    const { rerender } = render(<MoneyTimeline events={[]} />)
    expect(screen.getByText('Nothing has happened yet.')).toBeInTheDocument()
    rerender(<MoneyTimeline events={[{ id: 1, ts: '2026-10-06T10:00:00Z', kind: 'state', message: 'Buyer posted job' }, { id: 2, ts: '2026-10-06T10:00:05Z', kind: 'decision', message: 'Decision: VOID - integrity' }]} />)
    expect(screen.getAllByRole('listitem').filter((li) => li.textContent)).toHaveLength(2)
    expect(screen.getByText('Decision: VOID - integrity')).toBeInTheDocument()
  })
})

describe('JobCard', () => {
  it('links to the job and shows state, bounty and role', () => {
    render(<MemoryRouter><JobCard job={makeJob({ state: 'ESCROW_LOCKED' })} role="buyer" /></MemoryRouter>)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/jobs/job_abc12345')
    expect(screen.getByText('Escrow locked')).toBeInTheDocument()
    expect(screen.getByText('$5.00')).toBeInTheDocument()
    expect(screen.getByText('buyer')).toBeInTheDocument()
  })
})
