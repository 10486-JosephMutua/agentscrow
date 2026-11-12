import { useEffect, useState } from 'react'
import * as api from '../api/client.js'
import { moneyState } from '../lib/format.js'

const EMPTY = { open: 0, held: 0, paid: 0, pending: 0, released: 0, counts: { open: 0, held: 0, paid: 0, pending: 0, released: 0 }, total: 0, loaded: false }

/** Totals across every public job: what is held in escrow, paid out, and released back. Polls quietly. */
export function summarizeLedger(jobs) {
  const ledger = { ...EMPTY, counts: { ...EMPTY.counts }, total: jobs.length, loaded: true }
  for (const job of jobs) {
    const money = moneyState(job)
    const bucket = { none: 'open', held: 'held', settling: 'held', paid: 'paid', partial: 'paid', pending: 'pending', released: 'released' }[money.key]
    if (!bucket) continue
    ledger[bucket] += money.amount
    ledger.counts[bucket] += 1
  }
  return ledger
}

export function useLedger(intervalMs = 15000) {
  const [ledger, setLedger] = useState(EMPTY)
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .listJobs({ limit: 200 })
        .then((jobs) => alive && Array.isArray(jobs) && setLedger(summarizeLedger(jobs)))
        .catch(() => {})
    load()
    const timer = setInterval(load, intervalMs)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [intervalMs])
  return ledger
}
