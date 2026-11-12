import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cheatingVerdict, makeJob } from '../test/fixtures.js'

vi.mock('../api/client.js', () => ({
  ApiError: class ApiError extends Error {
    constructor(status, code, message, data = null) {
      super(message)
      this.status = status
      this.code = code
      this.data = data
    }
  },
  getJob: vi.fn(),
  getEvents: vi.fn(async () => []),
  openTimeline: vi.fn(() => () => {}),
  openEscrow: vi.fn(async () => ({})),
  confirmFunding: vi.fn(async () => ({})),
  runJob: vi.fn(async () => ({})),
  cancelJob: vi.fn(async () => ({})),
  arbitrateJob: vi.fn(async () => ({})),
  submitDeliverable: vi.fn(async () => ({})),
  rejectWorker: vi.fn(async () => ({})),
  withdraw: vi.fn(async () => ({})),
  acceptJob: vi.fn(async () => makeJob({ state: 'ACCEPTED' })),
  createJob: vi.fn(async () => makeJob()),
  getTemplates: vi.fn(async () => [
    { id: 'rle', title: 'Run-length encoding', summary: 'Compress runs.', signature: 'def rle_encode(s: str) -> str' },
    { id: 'roman', title: 'Roman numerals to integer', summary: 'MCMXCIV is 1994.', signature: 'def roman_to_int(s: str) -> int' },
  ]),
  validateTask: vi.fn(),
  getReceipt: vi.fn(),
  getHiddenTests: vi.fn(),
  verifyReceipt: vi.fn(),
  getReceiptKey: vi.fn(async () => ({ alg: 'Ed25519', key_id: 'abcd1234', public_key: 'PUBKEY' })),
  listJobs: vi.fn(async () => []),
  myJobs: vi.fn(async () => []),
  getHealth: vi.fn(async () => ({ paypal_mode: 'simulated', worker_mode: 'scripted', buyer_mode: 'direct' })),
  whoami: vi.fn(async () => ({ admin: false })),
  adminLogin: vi.fn(async () => ({})),
  adminLogout: vi.fn(async () => ({})),
  adminOverview: vi.fn(),
  adminJobs: vi.fn(async () => []),
  adminSweep: vi.fn(async () => ({ closed: [] })),
}))

const api = await import('../api/client.js')
const { default: JobPage } = await import('./JobPage.jsx')
const { default: CreateJobPage } = await import('./CreateJobPage.jsx')
const { default: ReceiptPage } = await import('./ReceiptPage.jsx')
const { default: JobBoardPage } = await import('./JobBoardPage.jsx')
const { default: AgentsPage } = await import('./AgentsPage.jsx')
const { default: OpsPage } = await import('./OpsPage.jsx')
const { default: App } = await import('../App.jsx')

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/jobs/:jobId" element={<JobPage />} />
        <Route path="/jobs/:jobId/receipt" element={<ReceiptPage />} />
        <Route path="/new" element={<CreateJobPage />} />
        <Route path="/jobs" element={<JobBoardPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/ops" element={<OpsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

const as = (roles, overrides = {}) => makeJob({ viewer: { roles }, ...overrides })

beforeEach(() => {
  vi.clearAllMocks()
  api.getEvents.mockResolvedValue([])
  api.openTimeline.mockReturnValue(() => {})
})

describe('JobPage as the buyer', () => {
  it('offers to open the escrow once a worker accepted, and does it', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'ACCEPTED', worker_id: 'w1' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.click(await screen.findByRole('button', { name: 'Open escrow' }))
    expect(api.openEscrow).toHaveBeenCalledWith('job_abc12345')
  })

  it('can reject a worker who accepted (so one griefer cannot block the job)', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'ACCEPTED', worker_id: 'griefer' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.click(await screen.findByRole('button', { name: /Reject griefer/ }))
    expect(api.rejectWorker).toHaveBeenCalledWith('job_abc12345')
  })

  it('links to PayPal to approve the hold', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'FUNDS_PENDING', approve_url: 'https://paypal.test/approve?token=O1' }))
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByRole('link', { name: 'Approve the hold in PayPal' })).toHaveAttribute('href', 'https://paypal.test/approve?token=O1')
    await userEvent.click(screen.getByRole('button', { name: /I have approved/ }))
    expect(api.confirmFunding).toHaveBeenCalled()
  })

  it('shows the PayPal "not approved yet" message from the server', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'FUNDS_PENDING', approve_url: 'https://paypal.test/a' }))
    api.confirmFunding.mockRejectedValueOnce(Object.assign(new Error('The buyer has not approved the PayPal order yet'), { status: 409 }))
    renderAt('/jobs/job_abc12345')
    await userEvent.click(await screen.findByRole('button', { name: /I have approved/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('has not approved')
  })

  it('lets the buyer pick a worker persona, shows its hint, and runs it', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'ESCROW_LOCKED' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.selectOptions(await screen.findByLabelText(/Which worker agent/), 'cheater')
    expect(screen.getByText(/Tries to sway the judge/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Run worker agent' }))
    expect(api.runJob).toHaveBeenCalledWith('job_abc12345', 'cheater')
    expect(screen.getByText('Held in escrow')).toBeInTheDocument()
  })

  it('shows a voided verdict, with the cheater caught and a receipt link', async () => {
    api.getJob.mockResolvedValue(
      as(['buyer'], {
        state: 'VOIDED',
        verdict: cheatingVerdict,
        decision: { outcome: 'VOID', reason: 'Integrity violation', v_score: 0.3, capture_amount: '0.00', platform_fee: '0.00', worker_payout: '0.00' },
      }),
    )
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByTestId('outcome-banner')).toHaveTextContent('buyer was charged $0.00')
    expect(screen.getByTestId('integrity-strip')).toHaveTextContent('never run')
    expect(screen.getByRole('link', { name: 'View the verdict receipt' })).toHaveAttribute('href', '/jobs/job_abc12345/receipt')
  })

  it('offers a retry when arbitration needs review', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'NEEDS_REVIEW' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.click(await screen.findByRole('button', { name: 'Retry arbitration' }))
    expect(api.arbitrateJob).toHaveBeenCalled()
  })

  it('shows the hidden-test commitment on the brief', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'POSTED' }))
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByText(/Hidden tests committed/)).toBeInTheDocument()
    expect(screen.getByTitle('a'.repeat(64))).toBeInTheDocument()
  })

  it('hides the stale "funds locked" banner once the job has moved on', async () => {
    api.getJob.mockResolvedValue(as(['buyer'], { state: 'SETTLED' }))
    renderAt('/jobs/job_abc12345?funded=1')
    await screen.findByText(/Captured and the worker was paid/)
    expect(screen.queryByText(/PayPal confirmed the hold/)).not.toBeInTheDocument()
  })
})

describe('JobPage in other seats', () => {
  it('shows guests an accept form for open jobs, and accepts', async () => {
    api.getJob.mockResolvedValue(as([], { state: 'POSTED' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.type(await screen.findByLabelText('Your worker name'), 'codesmith')
    await userEvent.type(screen.getByLabelText(/PayPal email/), 'me@example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Accept this job' }))
    expect(api.acceptJob).toHaveBeenCalledWith('job_abc12345', { workerId: 'codesmith', workerEmail: 'me@example.com' })
  })

  it('tells guests they can only watch a job in progress', async () => {
    api.getJob.mockResolvedValue(as([], { state: 'ESCROW_LOCKED' }))
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByText(/viewing this job as a guest/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run worker agent' })).not.toBeInTheDocument()
  })

  it('shows workers the submit form when funds are locked', async () => {
    api.getJob.mockResolvedValue(as(['worker'], { state: 'ESCROW_LOCKED' }))
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByText('Or submit your own solution')).toBeInTheDocument()
  })

  it('lets a worker withdraw before funding', async () => {
    api.getJob.mockResolvedValue(as(['worker'], { state: 'ACCEPTED', worker_id: 'me' }))
    renderAt('/jobs/job_abc12345')
    await userEvent.click(await screen.findByRole('button', { name: 'Withdraw from this job' }))
    expect(api.withdraw).toHaveBeenCalledWith('job_abc12345')
  })

  it('lets someone holding both seats switch between them', async () => {
    api.getJob.mockResolvedValue(as(['buyer', 'worker'], { state: 'ACCEPTED' }))
    renderAt('/jobs/job_abc12345')
    expect(await screen.findByRole('button', { name: 'Open escrow' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Worker' }))
    expect(screen.getByText(/Waiting for the buyer to lock the funds/)).toBeInTheDocument()
  })

  it('handles missing jobs', async () => {
    api.getJob.mockRejectedValue(new api.ApiError(404, 'job_not_found', 'No job x'))
    renderAt('/jobs/job_missing')
    expect(await screen.findByText('Job not found')).toBeInTheDocument()
  })
})

describe('CreateJobPage', () => {
  it('posts a template job after validating the bounty', async () => {
    renderAt('/new')
    await userEvent.click(await screen.findByLabelText(/Roman numerals/))
    const bounty = screen.getByLabelText('Bounty (USD)')
    await userEvent.clear(bounty)
    await userEvent.type(bounty, '500')
    expect(screen.getByRole('button', { name: 'Post job' })).toBeDisabled()
    await userEvent.clear(bounty)
    await userEvent.type(bounty, '7.5')
    await userEvent.selectOptions(screen.getByLabelText(/Deadline/), '6')
    await userEvent.click(screen.getByRole('button', { name: 'Post job' }))
    expect(api.createJob).toHaveBeenCalledWith({ bountyUsd: '7.50', deadlineHours: 6, template: 'roman' })
  })

  it('requires a custom task to pass the sandbox check before it can be posted', async () => {
    api.validateTask.mockResolvedValue({ ok: true, ticket: 'TICKET-1', hidden_test_count: 4, checks: [{ name: 'Reference solution passes every hidden test', passed: true, detail: '4/4 passed' }] })
    renderAt('/new')
    await userEvent.click(await screen.findByLabelText(/Your own task/))
    expect(screen.getByRole('button', { name: 'Check the task first' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Load an example' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check the task in the sandbox' }))
    expect(await screen.findByText(/passed every check/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Post job' }))
    expect(api.createJob).toHaveBeenCalledWith(expect.objectContaining({ validationTicket: 'TICKET-1', task: expect.objectContaining({ function_name: 'double' }) }))
  })

  it('shows exactly which checks a bad task failed, and keeps posting disabled', async () => {
    api.validateTask.mockResolvedValue({ ok: false, ticket: null, checks: [{ name: 'Hidden tests reject a do-nothing stub', passed: false, detail: 'a stub that returns None passes 3 of 3 tests' }] })
    renderAt('/new')
    await userEvent.click(await screen.findByLabelText(/Your own task/))
    await userEvent.click(screen.getByRole('button', { name: 'Load an example' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check the task in the sandbox' }))
    expect(await screen.findByText('Hidden tests reject a do-nothing stub')).toBeInTheDocument()
    expect(screen.getByText(/passes 3 of 3 tests/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check the task first' })).toBeDisabled()
  })

  it('invalidates an earlier check when the task is edited', async () => {
    api.validateTask.mockResolvedValue({ ok: true, ticket: 'T', checks: [] })
    renderAt('/new')
    await userEvent.click(await screen.findByLabelText(/Your own task/))
    await userEvent.click(screen.getByRole('button', { name: 'Load an example' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check the task in the sandbox' }))
    await screen.findByText(/passed every check/)
    await userEvent.type(screen.getByLabelText('Title'), '!')
    expect(screen.queryByText(/passed every check/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check the task first' })).toBeDisabled()
  })
})

describe('ReceiptPage', () => {
  const receipt = {
    signature: 'abc123', alg: 'Ed25519', key_id: 'abcd1234',
    receipt: {
      job_id: 'job_abc12345', title: 'Run-length encoding', outcome: 'FULL', reason: 'V=0.97: all hidden tests passed', simulated: true,
      bounty_usd: '5.00', buyer_charged_usd: '5.00', worker_payout_usd: '4.67', platform_fee_usd: '0.33', v_score: 0.97,
      tiers: { integrity: { ok: true }, sandbox: { passed: 9, total: 9 } },
      paypal: { order_id: 'O1', authorization_id: 'A1', capture_id: 'C1', payout_batch_id: 'P1' }, deliverable_sha256: 'deadbeef',
      hidden_tests_sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    },
  }

  it('renders a signed receipt, flagging simulation', async () => {
    api.getReceipt.mockResolvedValue(receipt)
    renderAt('/jobs/job_abc12345/receipt')
    expect(await screen.findByText('Paid in full')).toBeInTheDocument()
    expect(screen.getByText(/no money moved/)).toBeInTheDocument()
    expect(screen.getByText('9 of 9 passed')).toBeInTheDocument()
    expect(screen.getByText('abc123')).toBeInTheDocument()
  })

  it('verifies the signature and reports a forged receipt', async () => {
    api.getReceipt.mockResolvedValue(receipt)
    api.verifyReceipt.mockResolvedValueOnce({ valid: true }).mockResolvedValueOnce({ valid: false })
    renderAt('/jobs/job_abc12345/receipt')
    await userEvent.click(await screen.findByRole('button', { name: 'Verify signature' }))
    expect(await screen.findByText(/signature is valid/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Verify signature' }))
    expect(await screen.findByText(/does NOT match/)).toBeInTheDocument()
  })

  it('reveals the hidden tests and checks them against the commitment', async () => {
    api.getReceipt.mockResolvedValue(receipt)
    api.getHiddenTests.mockResolvedValue({ tests: 'abc', sha256: receipt.receipt.hidden_tests_sha256, matches_commitment: true })
    renderAt('/jobs/job_abc12345/receipt')
    await userEvent.click(await screen.findByRole('button', { name: 'Reveal hidden tests' }))
    expect(await screen.findByText(/committed to before the work started/)).toBeInTheDocument()
    expect(screen.getByLabelText('Revealed hidden tests')).toHaveTextContent('abc')
  })

  it('flags tests that do not match the commitment', async () => {
    api.getReceipt.mockResolvedValue(receipt)
    api.getHiddenTests.mockResolvedValue({ tests: 'altered', sha256: 'x', matches_commitment: false })
    renderAt('/jobs/job_abc12345/receipt')
    await userEvent.click(await screen.findByRole('button', { name: 'Reveal hidden tests' }))
    expect(await screen.findByText(/do NOT match the commitment/)).toBeInTheDocument()
  })

  it('explains when there is no receipt yet', async () => {
    api.getReceipt.mockRejectedValue(new api.ApiError(409, 'conflict', 'not settled'))
    renderAt('/jobs/job_abc12345/receipt')
    expect(await screen.findByText('No receipt yet')).toBeInTheDocument()
  })
})

describe('JobBoardPage', () => {
  it('shows an empty state, then jobs with a tag for the ones I can act on', async () => {
    const { unmount } = renderAt('/jobs')
    expect(await screen.findByText('No jobs here yet')).toBeInTheDocument()
    unmount()
    api.listJobs.mockResolvedValue([makeJob(), makeJob({ job_id: 'job_two', state: 'SETTLED' })])
    api.myJobs.mockResolvedValue([{ job_id: 'job_two', roles: ['buyer', 'worker'] }])
    renderAt('/jobs')
    expect(await screen.findAllByRole('link', { name: /Run-length encoding/ })).toHaveLength(2)
    expect(await screen.findByText('buyer + worker')).toBeInTheDocument()
  })

  it('filters by state', async () => {
    renderAt('/jobs')
    await userEvent.click(await screen.findByRole('tab', { name: 'Open' }))
    await waitFor(() => expect(api.listJobs).toHaveBeenLastCalledWith({ states: ['POSTED'], limit: 60 }))
  })
})

describe('AgentsPage', () => {
  it('documents the marketplace tools and shows the public receipt key', async () => {
    renderAt('/agents')
    expect((await screen.findAllByText('submit_solution')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('check_funding').length).toBeGreaterThan(0)
    expect(await screen.findByText('abcd1234')).toBeInTheDocument()
    expect(screen.getByText(/discovery card only/)).toBeInTheDocument()
  })
})

describe('OpsPage', () => {
  it('asks for the operator token, logs in for a cookie, then shows the console', async () => {
    api.whoami.mockResolvedValueOnce({ admin: false }).mockResolvedValue({ admin: true })
    api.adminOverview.mockResolvedValue({ counts: { SETTLED: 2, VOIDED: 1 }, captured_usd: '10.00', paid_to_workers_usd: '9.34', platform_fees_usd: '0.66' })
    renderAt('/ops')
    await userEvent.type(await screen.findByLabelText('Operator token'), 'the-admin-token-123')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    expect(api.adminLogin).toHaveBeenCalledWith('the-admin-token-123')
    expect(await screen.findByText('Needs attention (0)')).toBeInTheDocument()
    expect(screen.getByText('$10.00')).toBeInTheDocument()
  })

  it('shows a wrong token as an error', async () => {
    api.whoami.mockResolvedValue({ admin: false })
    api.adminLogin.mockRejectedValueOnce(new api.ApiError(401, 'unauthorized', 'That operator token is not valid'))
    renderAt('/ops')
    await userEvent.type(await screen.findByLabelText('Operator token'), 'wrong-token-value')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid')
  })
})

describe('App', () => {
  it('routes unknown addresses to a friendly 404 and shows the PayPal mode', async () => {
    render(<MemoryRouter initialEntries={['/nope']}><App /></MemoryRouter>)
    expect(await screen.findByText('Page not found')).toBeInTheDocument()
    expect(await screen.findByText('Simulated PayPal')).toBeInTheDocument()
  })
})
