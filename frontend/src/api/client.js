// The one place the UI talks to the AgentEscrow API. Pure JavaScript (no React) so Node scripts can reuse it.
//
// Authentication: in a browser the server keeps your access in an HttpOnly cookie, so this code never sees or stores a
// token (page scripts, including injected ones, cannot read the cookie). Outside a browser (Node scripts, agents) the
// server's bearer tokens are kept in memory and sent in the Authorization header.

const IS_BROWSER = typeof window !== 'undefined' && typeof window.document !== 'undefined'

let baseUrl = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE) || ''
let fetchImpl = (...args) => globalThis.fetch(...args)
let useBearer = !IS_BROWSER
let bearers = new Map() // job id -> { buyer, worker }
let adminBearer = ''

/** Point the client at another server or fetch implementation (tests, smoke script). */
export function configure({ baseUrl: url, fetch: impl, bearerMode } = {}) {
  if (url !== undefined) baseUrl = url.replace(/\/$/, '')
  if (impl) fetchImpl = impl
  if (bearerMode !== undefined) useBearer = bearerMode
  bearers = new Map()
  adminBearer = ''
}

/** Use the operator token as a bearer (non-browser clients only; browsers use `adminLogin`). */
export function setAdminBearer(token) {
  adminBearer = token
}

export class ApiError extends Error {
  constructor(status, code, message, data = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.data = data
  }
}

function bearerFor(jobId, roles = ['buyer', 'worker']) {
  if (!useBearer) return undefined
  const held = bearers.get(jobId) ?? {}
  for (const role of roles) if (held[role]) return held[role]
  return adminBearer || undefined
}

async function request(path, { method = 'GET', body, token, query } = {}) {
  const url = new URL(`${baseUrl}${path}`, globalThis.location?.origin ?? 'http://localhost')
  for (const [key, value] of Object.entries(query ?? {})) {
    for (const item of [].concat(value)) if (item !== undefined && item !== null) url.searchParams.append(key, item)
  }
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetchImpl(baseUrl ? url.toString() : `${url.pathname}${url.search}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: baseUrl ? 'include' : 'same-origin',
    })
  } catch {
    throw new ApiError(0, 'network', 'Cannot reach the AgentEscrow server. Is it running?')
  }

  let data = null
  try {
    data = await response.json()
  } catch {
    /* an empty or non-JSON body */
  }
  if (!response.ok) {
    throw new ApiError(response.status, data?.error ?? 'error', data?.message ?? `Request failed (${response.status})`, data)
  }
  return data
}

function remember(jobId, role, token) {
  if (!useBearer || !token) return
  bearers.set(jobId, { ...(bearers.get(jobId) ?? {}), [role]: token })
}

// ------------------------------------------------------------------ public ----
export const getHealth = () => request('/api/health')
export const getReady = () => request('/api/ready')
export const getTemplates = () => request('/api/templates')
export const getSiteOptions = () => request('/api/site/options')
export const listJobs = ({ states, limit } = {}) => request('/api/jobs', { query: { state: states, limit } })
export const myJobs = () => request('/api/me/jobs')
export const getJob = (jobId) => request(`/api/jobs/${jobId}`, { token: bearerFor(jobId) })
export const getEvents = (jobId, after = 0) => request(`/api/jobs/${jobId}/events`, { query: { after } })
export const getReceipt = (jobId) => request(`/api/jobs/${jobId}/receipt`)
export const getHiddenTests = (jobId) => request(`/api/jobs/${jobId}/hidden-tests`)
export const whoami = () => request('/api/whoami')
export const getReceiptKey = () => request('/.well-known/agentescrow-receipt-key.json')
export const verifyReceipt = (document) => request('/api/receipts/verify', { method: 'POST', body: document })

/** Lint a custom task in the sandbox. Always resolves with the report `{ ok, checks, hidden_test_count, ticket }`; `ok` says whether it passed. */
export const validateTask = (task) => request('/api/tasks/validate', { method: 'POST', body: task })

/**
 * Post a job from a template (`template`) or a validated custom task (`task` + `validationTicket`).
 * The server gives this browser the buyer seat. Returns the job.
 */
export async function createJob({ bountyUsd, deadlineHours, template, task, validationTicket, site } = {}) {
  const body = {}
  if (bountyUsd !== undefined && bountyUsd !== '') body.bounty_usd = String(bountyUsd)
  if (deadlineHours !== undefined && deadlineHours !== '') body.deadline_hours = Number(deadlineHours)
  if (template) body.template = template
  if (task) body.task = task
  if (site) body.site = site
  if (validationTicket) body.validation_ticket = validationTicket
  const { job, token, role } = await request('/api/jobs', { method: 'POST', body })
  remember(job.job_id, role, token)
  return job
}

/** Accept a job as a worker. The server gives this browser the worker seat. Returns the job. */
export async function acceptJob(jobId, { workerId, workerEmail }) {
  const { job, token, role } = await request(`/api/jobs/${jobId}/accept`, {
    method: 'POST',
    body: { worker_id: workerId, worker_email: workerEmail },
  })
  remember(jobId, role, token)
  return job
}

// --------------------------------------------------------- authenticated actions ----
// Each action says which roles may perform it (see the route table in agentescrow/api/app.py).
const act = (jobId, action, roles, body) =>
  request(`/api/jobs/${jobId}/${action}`, { method: 'POST', body, token: bearerFor(jobId, roles) })
export const openEscrow = (jobId) => act(jobId, 'escrow', ['buyer'])
export const confirmFunding = (jobId) => act(jobId, 'confirm-funding', ['buyer'])
export const cancelJob = (jobId) => act(jobId, 'cancel', ['buyer'])
export const rejectWorker = (jobId) => act(jobId, 'reject-worker', ['buyer'])
export const withdraw = (jobId) => act(jobId, 'withdraw', ['worker'])
export const runJob = (jobId, persona) => act(jobId, 'run', ['buyer', 'worker'], { persona })
export const submitDeliverable = (jobId, deliverable) => act(jobId, 'submit', ['worker'], deliverable)
export const arbitrateJob = (jobId) => act(jobId, 'arbitrate', ['buyer', 'worker'])

// ------------------------------------------------------------------ operator ----
const operator = () => (useBearer ? adminBearer || undefined : undefined)
export const adminLogin = (token) => request('/api/admin/login', { method: 'POST', body: { token } })
export const adminLogout = () => request('/api/admin/logout', { method: 'POST' })
export const adminOverview = () => request('/api/admin/overview', { token: operator() })
export const adminJobs = ({ states } = {}) => request('/api/admin/jobs', { token: operator(), query: { state: states } })
export const adminSweep = () => request('/api/admin/sweep', { method: 'POST', token: operator() })

/** Open the live timeline (Server-Sent Events). Returns a function that closes it. */
export function openTimeline(jobId, { after = 0, onEvent, onEnd, onError } = {}) {
  if (typeof EventSource === 'undefined') return () => {}
  const source = new EventSource(`${baseUrl}/api/jobs/${jobId}/stream?after=${after}`)
  source.addEventListener('timeline', (message) => onEvent?.(JSON.parse(message.data)))
  source.addEventListener('end', () => {
    source.close()
    onEnd?.()
  })
  source.onerror = (error) => onError?.(error) // EventSource reconnects by itself
  return () => source.close()
}
