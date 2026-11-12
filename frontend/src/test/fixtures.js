// Job objects shaped like the API's role-redacted views (see agentescrow/domain/models.py: Job.view).
export const spec = {
  title: 'Run-length encoding',
  description: 'Implement rle_encode(s) in solution.py.',
  function_name: 'rle_encode',
  function_signature: 'def rle_encode(s: str) -> str',
  module_name: 'solution',
  acceptance_criteria: ['Must pass the buyer hidden pytest suite', 'Pure function only'],
  public_tests: 'from solution import rle_encode\n\ndef test_basic():\n    assert rle_encode("aaabcc") == "a3b1c2"\n',
  required_schema: {},
}

export function makeJob(overrides = {}) {
  return {
    job_id: 'job_abc12345',
    state: 'POSTED',
    contract: { task_id: 'job_abc12345', task_type: 'python_function', bounty_usd: '5.00', deadline_epoch: Math.floor(Date.now() / 1000) + 3600, hidden_tests_sha256: 'a'.repeat(64), specification: spec },
    worker_id: null,
    deliverable_submitted: false,
    viewer: { roles: [] },
    verdict: null,
    decision: null,
    ...overrides,
  }
}

export const passingVerdict = {
  schema_check: { valid: true, errors: [], score: 1 },
  integrity: { ok: true, findings: [] },
  sandbox: { backend: 'docker', passed: 8, failed: 0, total: 8, timed_out: false, score: 1 },
  semantic: { clarity: 0.9, relevance: 0.9, thoroughness: 0.9, score: 0.9, rationale: 'Clear and complete.', judge: 'static', manipulation_suspected: false },
  v_score: 0.97,
  tiers_skipped: [],
}

export const cheatingVerdict = {
  schema_check: { valid: true, errors: [], score: 1 },
  integrity: { ok: false, findings: ['explanation: possible prompt injection (note-to-evaluator)'] },
  sandbox: null,
  semantic: null,
  v_score: 0.3,
  tiers_skipped: ['sandbox', 'semantic'],
}
