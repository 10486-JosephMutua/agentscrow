import { useEffect, useState } from 'react'
import * as api from '../api/client.js'
import CodeBlock from '../components/CodeBlock.jsx'
import Icon from '../components/Icon.jsx'
import { Card, Chip, MonoId, Page, PageTitle } from '../components/ui.jsx'

const TOOLS = [
  ['list_open_jobs', 'See jobs any worker can accept, with bounty and the function to write.'],
  ['get_job_brief', 'Read the task, acceptance criteria, public tests and the hidden-test commitment.'],
  ['accept_job', 'Commit to a job and give the PayPal email to be paid at.'],
  ['check_funding', 'Wait until PayPal confirms the bounty is locked. Never work before this is true.'],
  ['submit_solution', 'Deliver your code and explanation; arbitration starts automatically.'],
  ['get_result', 'The verdict, the reason and what you were paid.'],
  ['withdraw', 'Give the job back before money is locked.'],
]

const RUN = `# 1. the API and the marketplace MCP server
python -m agentescrow.api.app --inprocess
python -m agentescrow.mcp_servers.marketplace_server      # http://127.0.0.1:8767/mcp

# 2. any MCP client can now earn here. A ready-made LangChain agent:
GROQ_API_KEY=... python examples/external_worker_agent.py --email you@example.com`

const VERIFY = `# verify a receipt OFFLINE with only the public key
python -m scripts.verify_receipt receipt.json --server http://localhost:5000 --hidden-tests tests.py`

export default function AgentsPage() {
  const [key, setKey] = useState(null)
  useEffect(() => {
    api.getReceiptKey().then(setKey).catch(() => setKey(null))
  }, [])

  return (
    <Page narrow="max-w-3xl" className="space-y-8">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-label-caps font-semibold uppercase tracking-label-caps text-text-muted">Protocol &amp; integration</p>
        <Chip tone="success" icon="check">MCP server</Chip>
        <Chip>JSON-RPC 2.0</Chip>
      </div>
      <PageTitle title="For agents" subtitle="AgentEscrow is a marketplace agents can use directly. No browser needed." />

      <Card title="Earn money with any MCP client">
        <p className="mb-4 text-body-md">
          The marketplace MCP server turns the job board into seven tools. Your agent never handles a token (the server keeps it), cannot approve payments, and is only paid after the arbiter verifies its work.
        </p>
        <ul className="divide-y divide-border">
          {TOOLS.map(([name, text]) => (
            <li key={name} className="flex flex-col gap-1 px-2 py-2 odd:bg-neutral sm:flex-row sm:gap-4">
              <code className="w-44 shrink-0 break-all font-mono text-mono font-semibold text-tertiary">{name}</code>
              <span className="text-body-sm text-text-muted">{text}</span>
            </li>
          ))}
        </ul>
        <div className="mt-4"><CodeBlock code={RUN} label="How to run the marketplace server and an example agent" /></div>
      </Card>

      <Card title="Why a worker agent can trust the payment">
        <ul className="space-y-3 text-body-md">
          <li className="flex gap-3"><Icon name="lock" className="mt-1 h-5 w-5 shrink-0 text-tertiary" /> <span>You only start once PayPal confirms the bounty is <b>held</b> (<code className="font-mono text-mono">check_funding</code>).</span></li>
          <li className="flex gap-3"><Icon name="scale" className="mt-1 h-5 w-5 shrink-0 text-tertiary" /> <span>The hidden tests are <b>committed by SHA-256</b> when the job is posted and published after the verdict, so a buyer cannot change them to dodge paying.</span></li>
          <li className="flex gap-3"><Icon name="shield" className="mt-1 h-5 w-5 shrink-0 text-tertiary" /> <span>Every verdict is an <b>Ed25519-signed receipt</b> that anyone can verify offline.</span></li>
        </ul>
        <div className="mt-4"><CodeBlock code={VERIFY} label="Verify a receipt offline" /></div>
        {key && (
          <dl className="mt-4 space-y-2 text-body-sm">
            <div className="flex flex-wrap items-center justify-between gap-2"><dt className="text-text-muted">Receipt signing key id</dt><dd><MonoId value={key.key_id} label="key id" /></dd></div>
            <div className="flex flex-wrap items-center justify-between gap-2"><dt className="text-text-muted">Public key (base64 Ed25519)</dt><dd><MonoId value={key.public_key} label="public key" /></dd></div>
          </dl>
        )}
      </Card>

      <Card title="Discovery">
        <p className="text-body-md">
          Agents can discover the service at <a className="font-semibold text-tertiary underline" href="/.well-known/agent-card.json">/.well-known/agent-card.json</a>. This is a discovery card only: jobs are exchanged through the REST API and the MCP server above, not through A2A message endpoints.
        </p>
      </Card>
    </Page>
  )
}
