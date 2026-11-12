// API smoke test: drives a RUNNING AgentEscrow server with the very client module the UI uses (in bearer mode, as a script would).
//   (project root)  PAYPAL_MODE=simulated WORKER_MODE=scripted ... python -m agentescrow.api.app --inprocess
//   (frontend)      API_BASE=http://127.0.0.1:5000 ADMIN_TOKEN=... npm run smoke
// Exits non-zero on any failure. Requires PAYPAL_MODE=simulated (no browser approval step).
import { createHash } from 'node:crypto'
import * as api from '../src/api/client.js'

const BASE = process.env.API_BASE ?? 'http://127.0.0.1:5000'
api.configure({ baseUrl: BASE })

const log = (message) => console.log(`  ${message}`)
function check(condition, message) {
  if (!condition) throw new Error(`FAILED: ${message}`)
  log(`ok - ${message}`)
}

async function waitForState(jobId, states, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const job = await api.getJob(jobId)
    if (states.includes(job.state)) return job
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
  throw new Error(`FAILED: job ${jobId} did not reach ${states}`)
}

async function fundedJob(options) {
  const job = await api.createJob({ bountyUsd: '5.00', deadlineHours: 2, ...options })
  await api.acceptJob(job.job_id, { workerId: 'smoke-agent', workerEmail: 'payouts-simulator-receiver@paypal.com' })
  const funding = await api.openEscrow(job.job_id)
  check(funding.state === 'FUNDS_PENDING' && funding.approve_url, 'escrow order created with an approval link')
  const back = await fetch(`${BASE}/escrow/success?job_id=${job.job_id}`, { redirect: 'manual' }) // PayPal sends the buyer back here
  check(back.status === 302 && (await api.getJob(job.job_id)).state === 'ESCROW_LOCKED', 'the return URL locks the funds after PayPal confirms')
  return job.job_id
}

async function run(label, options, persona, expectedState, expectedOutcome) {
  console.log(`\n${label}`)
  const jobId = await fundedJob(options)
  await api.runJob(jobId, persona)
  const done = await waitForState(jobId, ['SETTLED', 'VOIDED', 'NEEDS_REVIEW'])
  check(done.state === expectedState && done.decision?.outcome === expectedOutcome, `${persona} -> ${done.state} / ${done.decision?.outcome}`)
  const document = await api.getReceipt(jobId)
  check(document.alg === 'Ed25519' && (await api.verifyReceipt(document)).valid, 'the signed receipt verifies')
  const tampered = JSON.parse(JSON.stringify(document))
  tampered.receipt.worker_payout_usd = '9999.00'
  check(!(await api.verifyReceipt(tampered)).valid, 'a tampered receipt is rejected')
  const revealed = await api.getHiddenTests(jobId)
  const digest = createHash('sha256').update(revealed.tests, 'utf8').digest('hex')
  check(revealed.matches_commitment && digest === document.receipt.hidden_tests_sha256, 'the revealed hidden tests match the commitment made when the job was posted')
  return jobId
}

async function main() {
  const health = await api.getHealth()
  console.log(`API ${BASE}: paypal=${health.paypal_mode} worker=${health.worker_mode} sandbox=${health.sandbox_backend}`)
  if (health.paypal_mode !== 'simulated') throw new Error('The smoke test needs PAYPAL_MODE=simulated (no browser approval)')
  const ready = await api.getReady()
  check(ready.ready, 'the server reports itself ready')
  const templates = await api.getTemplates()
  check(templates.length === 3, `${templates.length} templates are offered`)

  const honest = await run('rle / honest', { template: 'rle' }, 'honest', 'SETTLED', 'FULL')
  await run('rle / sloppy', { template: 'rle' }, 'sloppy', 'SETTLED', 'PARTIAL')
  await run('rle / cheater', { template: 'rle' }, 'cheater', 'VOIDED', 'VOID')
  await run('roman / honest', { template: 'roman' }, 'honest', 'SETTLED', 'FULL')
  await run('brackets / sloppy', { template: 'brackets' }, 'sloppy', 'SETTLED', 'PARTIAL')

  console.log('\ncustom task')
  const task = {
    title: 'Double a number', description: 'Implement double(x) returning twice the integer x. Negative numbers and zero must work too.',
    function_name: 'double', function_signature: 'def double(x: int) -> int',
    public_tests: 'from solution import double\n\n\ndef test_two():\n    assert double(2) == 4\n',
    hidden_tests: 'from solution import double\n\n\ndef test_zero():\n    assert double(0) == 0\n\n\ndef test_negative():\n    assert double(-3) == -6\n\n\ndef test_large():\n    assert double(10**6) == 2 * 10**6\n',
    reference_solution: 'def double(x: int) -> int:\n    return x * 2\n',
  }
  const vacuous = await api.validateTask({ ...task, hidden_tests: 'from solution import double\n\n\ndef test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n\n\ndef test_c():\n    assert True\n' })
  check(!vacuous.ok && vacuous.checks.some((c) => !c.passed && /do-nothing stub/.test(c.name)), 'vacuous tests are rejected')
  const report = await api.validateTask(task)
  check(report.ok && report.ticket, 'a sound custom task passes the sandbox lint')
  const custom = await fundedJob({ task, validationTicket: report.ticket })
  await api.runJob(custom, 'honest')
  const paid = await waitForState(custom, ['SETTLED', 'VOIDED'])
  check(paid.decision?.outcome === 'FULL' && !JSON.stringify(paid).includes('reference_solution'), 'the custom task is paid in full and the reference solution is never exposed')

  console.log('\nredaction and permissions')
  const anon = JSON.stringify(await (await fetch(`${BASE}/api/jobs/${honest}`)).json())
  check(!anon.includes('"hidden_tests":') && !anon.includes('mandate_token') && !anon.includes('worker_email') && !anon.includes('SIM-AUTH'), 'the public view hides secrets')
  check((await fetch(`${BASE}/api/jobs/${honest}/cancel`, { method: 'POST' })).status === 401, 'actions without access are refused (401)')
  const forged = await fetch(`${BASE}/api/jobs/${honest}/cancel`, { method: 'POST', headers: { Origin: 'https://evil.example' } })
  check(forged.status === 403 || forged.status === 401, 'a forged cross-origin request is refused')

  if (process.env.ADMIN_TOKEN) {
    api.setAdminBearer(process.env.ADMIN_TOKEN)
    const overview = await api.adminOverview()
    check(Number(overview.counts.SETTLED) >= 4 && Number(overview.counts.VOIDED) >= 1, 'the operator overview counts the jobs')
  }

  console.log('\nbuilt UI and discovery')
  const index = await fetch(`${BASE}/jobs/anything`)
  check(index.ok && (await index.text()).includes('<div id="root">'), 'the React app is served with client-side routing')
  const card = await (await fetch(`${BASE}/.well-known/agent-card.json`)).json()
  check(card.name === 'AgentEscrow' && card.skills.length >= 3, 'the discovery card is published')
  console.log('\nSMOKE TEST PASSED')
}

main().catch((error) => {
  console.error(`\n${error.message}`)
  process.exit(1)
})
