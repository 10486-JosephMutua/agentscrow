import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './client.js'

function fakeFetch(handler) {
  const calls = []
  const impl = vi.fn(async (url, init) => {
    calls.push({ url, init })
    const { status = 200, body = {} } = handler(url, init, calls.length)
    return { ok: status < 400, status, json: async () => body }
  })
  return { calls, impl }
}

function setup(handler, bearerMode) {
  const fake = fakeFetch(handler)
  api.configure({ baseUrl: '', fetch: fake.impl, bearerMode })
  return fake.calls
}

describe('in a browser (cookie sessions)', () => {
  it('never sends or stores a token: the server keeps access in an HttpOnly cookie', async () => {
    const calls = setup(() => ({ status: 201, body: { job: { job_id: 'job_1' }, token: 'SECRET-TOKEN', role: 'buyer' } }), false)
    await api.createJob({ bountyUsd: '7.50', deadlineHours: '6', template: 'roman' })
    await api.openEscrow('job_1')
    await api.runJob('job_1', 'honest')
    expect(calls.every((call) => call.init.headers.Authorization === undefined)).toBe(true)
    expect(calls.every((call) => call.init.credentials === 'same-origin')).toBe(true)
    expect(JSON.stringify(localStorage)).not.toContain('SECRET-TOKEN')
    expect(JSON.parse(calls[0].init.body)).toEqual({ bounty_usd: '7.50', deadline_hours: 6, template: 'roman' })
  })

  it('posts a validated custom task with its ticket', async () => {
    const calls = setup(() => ({ status: 201, body: { job: { job_id: 'job_2' }, token: 't', role: 'buyer' } }), false)
    await api.createJob({ bountyUsd: '5', task: { title: 'T' }, validationTicket: 'TICKET' })
    expect(JSON.parse(calls[0].init.body)).toMatchObject({ task: { title: 'T' }, validation_ticket: 'TICKET' })
  })

  it('operators log in for a cookie instead of keeping a token', async () => {
    const calls = setup(() => ({ body: { role: 'admin' } }), false)
    await api.adminLogin('the-admin-token')
    await api.adminOverview()
    expect(JSON.parse(calls[0].init.body)).toEqual({ token: 'the-admin-token' })
    expect(calls[1].init.headers.Authorization).toBeUndefined()
  })
})

describe('outside a browser (bearer tokens, in memory)', () => {
  it('createJob keeps the buyer token and uses it only for buyer actions', async () => {
    const calls = setup((url) => (url.includes('/api/jobs') && !url.includes('/escrow') ? { status: 201, body: { job: { job_id: 'job_1' }, token: 'B', role: 'buyer' } } : { body: {} }), true)
    await api.createJob({})
    await api.openEscrow('job_1')
    expect(calls[1].init.headers.Authorization).toBe('Bearer B')
  })

  it('holds buyer and worker tokens for one job and picks the right one per action', async () => {
    const calls = setup((url) => {
      if (url.endsWith('/accept')) return { body: { job: { job_id: 'j' }, token: 'W', role: 'worker' } }
      if (url.endsWith('/api/jobs')) return { status: 201, body: { job: { job_id: 'j' }, token: 'B', role: 'buyer' } }
      return { body: {} }
    }, true)
    await api.createJob({})
    await api.acceptJob('j', { workerId: 'w', workerEmail: 'w@x.io' })
    await api.openEscrow('j')
    await api.submitDeliverable('j', { solution_code: 'x', explanation: 'y' })
    await api.runJob('j', 'honest')
    await api.withdraw('j')
    await api.rejectWorker('j')
    expect(calls.slice(2).map((call) => call.init.headers.Authorization)).toEqual(['Bearer B', 'Bearer W', 'Bearer B', 'Bearer W', 'Bearer B'])
  })

  it('guests send no Authorization header; tokens from other jobs are never reused', async () => {
    const calls = setup((url) => (url.endsWith('/api/jobs') ? { status: 201, body: { job: { job_id: 'a' }, token: 'A', role: 'buyer' } } : { body: [] }), true)
    await api.createJob({})
    await api.getJob('another-job')
    await api.listJobs({ states: ['POSTED', 'ACCEPTED'], limit: 10 })
    expect(calls[1].init.headers.Authorization).toBeUndefined()
    expect(calls[2].url).toContain('state=POSTED')
    expect(calls[2].url).toContain('state=ACCEPTED')
    expect(calls[2].url).toContain('limit=10')
  })

  it('uses the operator bearer for admin calls', async () => {
    const calls = setup(() => ({ body: {} }), true)
    api.setAdminBearer('ADMIN')
    await api.adminOverview()
    expect(calls[0].init.headers.Authorization).toBe('Bearer ADMIN')
  })
})

describe('errors', () => {
  beforeEach(() => api.configure({ baseUrl: '', bearerMode: false }))

  it('maps API errors and keeps the response body', async () => {
    setup(() => ({ status: 409, body: { error: 'conflict', message: 'Job is POSTED', extra: 1 } }), false)
    await expect(api.getJob('j')).rejects.toMatchObject({ name: 'ApiError', status: 409, code: 'conflict', message: 'Job is POSTED', data: { extra: 1 } })
  })

  it('a failed task lint is a normal report, not an error', async () => {
    setup(() => ({ body: { ok: false, ticket: null, checks: [{ name: 'c', passed: false }] } }), false)
    await expect(api.validateTask({})).resolves.toMatchObject({ ok: false, checks: [{ name: 'c', passed: false }] })
  })

  it('explains network failures', async () => {
    api.configure({ fetch: async () => { throw new TypeError('failed') } })
    await expect(api.getHealth()).rejects.toMatchObject({ status: 0, code: 'network' })
  })
})
