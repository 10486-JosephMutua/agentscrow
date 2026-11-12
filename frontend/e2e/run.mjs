// Real-browser end-to-end tests: drives the built UI in headless Chrome against a RUNNING server (PAYPAL_MODE=simulated).
//
//   (project root)   PAYPAL_MODE=simulated WORKER_MODE=scripted BUYER_MODE=direct SEMANTIC_JUDGE=static ALLOW_UNSAFE_SANDBOX=true \
//                    ADMIN_TOKEN=... MANDATE_SECRET=... python -m agentescrow.api.app --inprocess
//   (frontend)       npm run build && BASE=http://127.0.0.1:5000 ADMIN_TOKEN=... npm run e2e
//
// Needs `npm i -D puppeteer-core` and either CHROME_PATH=/path/to/chrome or `npm i -D @sparticuz/chromium`.
import { mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://127.0.0.1:5000'
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? ''
const SHOTS = process.env.SHOTS ?? '/tmp/e2e'
mkdirSync(SHOTS, { recursive: true })

let puppeteer
try {
  puppeteer = (await import('puppeteer-core')).default
} catch {
  console.error('Install puppeteer-core first:  npm i -D puppeteer-core  (and set CHROME_PATH, or npm i -D @sparticuz/chromium)')
  process.exit(2)
}
let launchOptions
if (process.env.CHROME_PATH) {
  launchOptions = { executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'], headless: 'shell' }
} else {
  const chromium = (await import('@sparticuz/chromium')).default
  // The Lambda-oriented flags include --single-process, which cannot host several isolated browser contexts.
  const args = chromium.args.filter((flag) => flag !== '--single-process' && flag !== '--no-zygote')
  launchOptions = { args: [...args, '--no-sandbox'], executablePath: await chromium.executablePath(), headless: 'shell' }
}

const browser = await puppeteer.launch(launchOptions)
const problems = []
const results = []
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

let lastPage = null
async function newSession(label, viewport = { width: 1280, height: 900 }) {
  const context = await browser.createBrowserContext() // separate cookies, like a different person
  const page = await context.newPage()
  lastPage = page
  await page.setViewport(viewport)
  page.on('console', (m) => ['error', 'warning'].includes(m.type()) && problems.push(`[${label}] console.${m.type()}: ${m.text()}`))
  page.on('pageerror', (e) => problems.push(`[${label}] pageerror: ${e.message}`))
  page.on('requestfailed', (r) => !r.url().includes('/stream') && problems.push(`[${label}] requestfailed: ${r.url()} ${r.failure()?.errorText}`))
  return { page, context }
}

const text = (page) => page.evaluate(() => document.body.innerText.toLowerCase())
const waitText = (page, needle, timeout = 60000) => page.waitForFunction((n) => document.body.innerText.toLowerCase().includes(n), { timeout }, needle.toLowerCase())
async function click(page, label, tag = 'button') {
  const handle = await page.waitForSelector(`::-p-xpath(//${tag}[contains(normalize-space(.), "${label}")])`, { timeout: 20000 })
  await handle.click()
}
const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
const api = async (path, init) => (await fetch(`${BASE}${path}`, init)).json()

async function scenario(name, fn) {
  if (process.env.ONLY && !name.includes(process.env.ONLY)) return
  const started = Date.now()
  try {
    await fn()
    results.push({ name, ok: true, ms: Date.now() - started })
    console.log(`  ok   ${name} (${((Date.now() - started) / 1000).toFixed(1)}s)`)
  } catch (error) {
    results.push({ name, ok: false, error: error.message })
    console.log(`  FAIL ${name}\n       ${error.message.split('\n')[0]}`)
    if (lastPage) {
      const body = await lastPage.evaluate(() => document.body.innerText.replace(/\n+/g, ' | ')).catch(() => '')
      console.log(`       page was ${lastPage.url()}\n       text: ...${body.slice(-300)}`)
      await lastPage.screenshot({ path: `${SHOTS}/FAILED-${name.slice(0, 20).replace(/\W+/g, '-')}.png`, fullPage: true }).catch(() => {})
    }
  }
}
function check(condition, message) {
  if (!condition) throw new Error(`assertion failed: ${message}`)
}

const onJobPage = (page) => page.waitForFunction(() => location.pathname.startsWith('/jobs/'), { timeout: 20000 })
async function guidedDemo(page) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await click(page, 'Run the guided demo')
  await waitText(page, 'open escrow')
  await click(page, 'Open escrow')
  await waitText(page, 'approve the hold in paypal')
  await click(page, 'Approve the hold in PayPal', 'a')
  await waitText(page, 'run worker agent')
}

console.log(`Browser E2E against ${BASE}\n`)

await scenario('home page renders, dark card is readable, no console errors', async () => {
  const { page } = await newSession('home')
  await page.goto(BASE, { waitUntil: 'networkidle0' })
  check((await text(page)).includes('three possible endings'), 'the dark "Three possible endings" card shows its text')
  const contrast = await page.evaluate(() => {
    const heading = [...document.querySelectorAll('p')].find((el) => el.textContent.toLowerCase().includes('three possible endings'))
    const card = heading.closest('section')
    return { fg: getComputedStyle(heading).color, bg: getComputedStyle(card).backgroundColor }
  })
  check(contrast.fg !== contrast.bg, `card text colour ${contrast.fg} differs from its background ${contrast.bg}`)
  await shot(page, '01-home')
})

await scenario('guided demo: honest worker is paid in full, live timeline, HttpOnly session', async () => {
  const { page } = await newSession('demo')
  await guidedDemo(page)
  check(!(await page.evaluate(() => document.cookie)).includes('ae_session'), 'the session cookie is invisible to page scripts (HttpOnly)')
  check(!(await page.evaluate(() => JSON.stringify(localStorage))).includes('eyJ'), 'no token is kept in localStorage')
  const before = await page.$$eval('[aria-label="Job timeline"] li', (items) => items.length)
  await click(page, 'Run worker agent')
  await waitText(page, 'arbiter verdict')
  const after = await page.$$eval('[aria-label="Job timeline"] li', (items) => items.length)
  check(after >= before + 3, `the timeline grew live without a reload (${before} -> ${after})`)
  check((await text(page)).includes('paid in full'), 'outcome banner says paid in full')
  await shot(page, '02-demo-paid')
  await click(page, 'View the verdict receipt', 'a')
  await waitText(page, 'audit this verdict')
  await click(page, 'Verify signature')
  await waitText(page, 'signature is valid')
  await click(page, 'Reveal hidden tests')
  await waitText(page, 'committed to before the work started')
  check((await text(page)).includes('recomputed the sha-256'), 'the browser independently recomputed the commitment')
  await shot(page, '03-receipt-audit')
})

await scenario('a different template with a cheating worker is voided before it runs', async () => {
  const { page } = await newSession('roman')
  await page.goto(`${BASE}/new`, { waitUntil: 'networkidle0' })
  await click(page, 'Roman numerals to integer', 'label')
  await click(page, 'Post job')
  await onJobPage(page)
  await waitText(page, 'take the job yourself')
  await click(page, 'Take the job yourself', 'summary')
  await page.$eval('#worker-id', (el) => { el.value = '' })
  await page.type('#worker-id', 'cheat-bot')
  await click(page, 'Accept this job')
  await waitText(page, 'open escrow')
  await click(page, 'Open escrow')
  await waitText(page, 'approve the hold in paypal')
  await click(page, 'Approve the hold in PayPal', 'a')
  await waitText(page, 'run worker agent')
  await page.select('#persona', 'cheater')
  await click(page, 'Run worker agent')
  await waitText(page, 'buyer was charged $0.00')
  await waitText(page, 'integrity gate failed')
  const strip = await page.$eval('[data-testid="integrity-strip"]', (el) => el.innerText)
  check(strip.toLowerCase().includes('integrity gate failed'), `integrity gate failure is shown (strip says: ${strip.slice(0, 80)})`)
  await shot(page, '04-voided')
})

await scenario('custom task: bad tests are rejected with reasons, a good task is posted and paid', async () => {
  const { page } = await newSession('custom')
  await page.goto(`${BASE}/new`, { waitUntil: 'networkidle0' })
  await click(page, 'Your own task', 'label')
  await click(page, 'Load an example')
  // make the hidden tests vacuous: they would pass for ANY code
  await page.$eval('#t-hid', (el) => { el.value = '' })
  await page.type('#t-hid', 'from solution import double\n\n\ndef test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n\n\ndef test_c():\n    assert True\n')
  await click(page, 'Check the task in the sandbox')
  await waitText(page, 'hidden tests reject a do-nothing stub', 90000)
  check(await page.$eval('button[type=submit]', (el) => el.disabled), 'posting stays disabled for a bad task')
  await shot(page, '05-custom-rejected')
  await click(page, 'Load an example')
  await click(page, 'Check the task in the sandbox')
  await waitText(page, 'the task passed every check', 90000)
  await shot(page, '06-custom-validated')
  await click(page, 'Post job')
  await onJobPage(page)
  await waitText(page, 'take the job yourself')
  await click(page, 'Take the job yourself', 'summary')
  await click(page, 'Accept this job')
  await waitText(page, 'open escrow')
  await click(page, 'Open escrow')
  await waitText(page, 'approve the hold in paypal')
  await click(page, 'Approve the hold in PayPal', 'a')
  await waitText(page, 'run worker agent')
  await click(page, 'Run worker agent')
  await waitText(page, 'paid in full')
})

await scenario('a buyer can reject a worker; the old worker loses access', async () => {
  const buyer = await newSession('buyer')
  await buyer.page.goto(`${BASE}/new`, { waitUntil: 'networkidle0' })
  await click(buyer.page, 'Post job')
  await onJobPage(buyer.page)
  const jobUrl = buyer.page.url()
  const worker = await newSession('worker')
  await worker.page.goto(jobUrl, { waitUntil: 'domcontentloaded' })
  await worker.page.waitForSelector('#worker-id')
  await worker.page.type('#worker-id', 'griefer')
  await worker.page.type('#worker-email', 'griefer@example.com')
  await click(worker.page, 'Accept this job')
  await waitText(worker.page, 'withdraw from this job')
  await buyer.page.reload({ waitUntil: 'domcontentloaded' })
  await click(buyer.page, 'Reject griefer')
  await waitText(buyer.page, 'waiting for a worker to accept')
  await worker.page.reload({ waitUntil: 'domcontentloaded' })
  await waitText(worker.page, 'accept this job')
  check((await text(worker.page)).includes('accept this job'), 'the rejected worker is a guest again and sees the accept form')
  await shot(worker.page, '07-rejected-worker')
})

await scenario('cross-site request forgery is blocked by SameSite=Strict + the Origin check', async () => {
  const { page } = await newSession('victim')
  await page.goto(`${BASE}/new`, { waitUntil: 'networkidle0' })
  await click(page, 'Post job')
  await onJobPage(page)
  const jobId = page.url().split('/jobs/')[1].split('?')[0]
  const attacker = await page.browserContext().newPage() // same cookies, but a page on another origin
  await attacker.goto('http://localhost:1/', { waitUntil: 'load' }).catch(() => {})
  await attacker.setContent('<h1>evil</h1>')
  const outcome = await attacker.evaluate(async (url) => {
    try {
      await fetch(url, { method: 'POST', credentials: 'include', mode: 'no-cors' })
      return 'sent'
    } catch (error) {
      return `blocked: ${error.message}`
    }
  }, `${BASE}/api/jobs/${jobId}/cancel`)
  await sleep(500)
  check((await api(`/api/jobs/${jobId}`)).state === 'POSTED', `the job survived the forged cancel (attacker fetch: ${outcome})`)
})

await scenario('operator login uses an HttpOnly cookie', async () => {
  if (!ADMIN_TOKEN) return console.log('       (skipped: set ADMIN_TOKEN)')
  const { page } = await newSession('ops')
  await page.goto(`${BASE}/ops`, { waitUntil: 'networkidle0' })
  await waitText(page, 'operator access')
  await page.type('input[type=password]', ADMIN_TOKEN)
  await click(page, 'Unlock')
  await waitText(page, 'needs attention')
  check(!(await page.evaluate(() => document.cookie)).includes('ae_admin'), 'the operator cookie is invisible to page scripts')
  await shot(page, '08-ops')
})

await scenario('agents page and 404', async () => {
  const { page } = await newSession('agents')
  await page.goto(`${BASE}/agents`, { waitUntil: 'networkidle0' })
  await waitText(page, 'submit_solution')
  await waitText(page, 'receipt signing key id')
  await shot(page, '09-agents')
  await page.goto(`${BASE}/definitely-not-a-page`, { waitUntil: 'networkidle0' })
  await waitText(page, 'page not found')
})

await scenario('mobile: no sideways scrolling, money card first', async () => {
  const { page } = await newSession('mobile', { width: 390, height: 844 })
  await guidedDemo(page)
  const metrics = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }))
  check(metrics.scroll <= metrics.view + 1, `no horizontal overflow (${metrics.scroll} <= ${metrics.view})`)
  const order = await page.evaluate(() => {
    const money = document.querySelector('[data-testid="money-amount"]').getBoundingClientRect().top
    const brief = [...document.querySelectorAll('h2')].find((el) => el.textContent.toLowerCase().includes('the job')).getBoundingClientRect().top
    return { money, brief }
  })
  check(order.money < order.brief, 'the money card appears above the job brief on a phone')
  await shot(page, '10-mobile-job')
})

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} scenarios passed`)
console.log(problems.length ? `\nbrowser problems:\n${problems.join('\n')}` : 'no console errors or failed requests')
process.exit(failed.length || problems.length ? 1 : 0)
