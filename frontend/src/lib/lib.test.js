import { describe, expect, it } from 'vitest'
import { formatDeadline, formatScore, formatUsd, moneyState, shortId } from './format.js'
import { finalStepLabel, isTerminal, STEPS, stateMeta, stepIndex } from './states.js'

describe('states', () => {
  it('knows every backend state', () => {
    for (const state of ['POSTED', 'ACCEPTED', 'FUNDS_PENDING', 'ESCROW_LOCKED', 'SUBMITTED', 'ARBITRATING', 'NEEDS_REVIEW', 'SETTLING', 'SETTLED', 'VOIDED', 'CANCELLED']) {
      expect(stateMeta(state).label).not.toBe(state === 'POSTED' ? '' : undefined)
      expect(stateMeta(state).tone).toBeTruthy()
    }
  })
  it('places states on the stepper', () => {
    expect(stepIndex('POSTED')).toBe(0)
    expect(stepIndex('ESCROW_LOCKED')).toBe(3)
    expect(stepIndex('NEEDS_REVIEW')).toBe(stepIndex('ARBITRATING'))
    for (const done of ['SETTLED', 'VOIDED', 'CANCELLED']) expect(stepIndex(done)).toBe(STEPS.length - 1)
  })
  it('labels the final step by outcome', () => {
    expect(finalStepLabel('VOIDED')).toBe('Voided')
    expect(finalStepLabel('SETTLED')).toBe('Settled')
    expect(isTerminal('VOIDED')).toBe(true)
    expect(isTerminal('SUBMITTED')).toBe(false)
  })
  it('falls back for unknown states', () => {
    expect(stateMeta('MYSTERY')).toMatchObject({ label: 'MYSTERY', tone: 'neutral' })
  })
})

describe('format', () => {
  it('formats money and scores', () => {
    expect(formatUsd('4.67')).toBe('$4.67')
    expect(formatUsd(undefined)).toBe('$0.00')
    expect(formatScore(0.97)).toBe('0.97')
    expect(formatScore(undefined)).toBe('–')
  })
  it('shortens long ids only', () => {
    expect(shortId('SIM-AUTH-ABCDEF123456')).toBe('SIM-AU…123456')
    expect(shortId('short')).toBe('short')
  })
  it('describes deadlines', () => {
    const now = Date.UTC(2026, 9, 6, 12, 0, 0)
    expect(formatDeadline(now / 1000 + 3 * 3600 + 20 * 60, now)).toBe('in 3h 20m')
    expect(formatDeadline(now / 1000 - 5 * 60, now)).toBe('5m ago')
    expect(formatDeadline(now / 1000 + 2 * 86400, now)).toBe('in 2d')
  })
  it('summarises where the money is', () => {
    const base = { contract: { bounty_usd: '5.00' } }
    expect(moneyState({ ...base, state: 'POSTED' })).toMatchObject({ key: 'none', amount: 5 })
    expect(moneyState({ ...base, state: 'ESCROW_LOCKED' })).toMatchObject({ key: 'held', tone: 'held', amount: 5 })
    expect(moneyState({ ...base, state: 'SETTLED', decision: { outcome: 'FULL', capture_amount: '5.00' } })).toMatchObject({ key: 'paid', amount: 5 })
    expect(moneyState({ ...base, state: 'SETTLED', decision: { outcome: 'PARTIAL', capture_amount: '4.10' } })).toMatchObject({ key: 'partial', amount: 4.1 })
    expect(moneyState({ ...base, state: 'VOIDED' })).toMatchObject({ key: 'released', amount: 0 })
  })
})
