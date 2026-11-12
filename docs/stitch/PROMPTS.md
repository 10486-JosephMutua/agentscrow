# Stitch prompt pack for AgentEscrow

Paste these into [Google Stitch](https://stitch.withgoogle.com) in order. They follow the "zoom out, then zoom in" approach:
first one prompt that explains the whole product, then one prompt per screen. Every prompt is self-contained and uses
realistic sample data, because Stitch designs look (and export) better with real content than with lorem ipsum.

> **Before you start:** import `DESIGN.md` from this folder as the design system if your Stitch project supports it
> (it carries the colors, type, spacing and component rules). If it does not, paste the **Design system prompt** below
> once at the start of the project.

The React app in `frontend/` already implements every screen, so you can run the product today. Stitch gives you a
second, more polished pass at the visuals; `README.md` in this folder explains how to port what Stitch generates.

---

## 0. Design system prompt (only if you cannot import DESIGN.md)

```
Design system for "AgentEscrow", a financial control room for escrow between AI agents.
Mood: calm, precise, trustworthy. Think bank statement crossed with mission-control console. No playful money visuals.

Colors: app bar and headings deep ink #0B1F2A; page background #F4F6F7; cards white with a 1px border #D5DEE2;
body text #14232C, secondary text #5B6B74. One brand accent: escrow teal #0B7A6B (the single main button per screen).
Status colors, each with a light container: HELD gold #8A5A0B on #FBF1DC (reserved ONLY for money locked in escrow),
SUCCESS green #146C3B on #DFF4E7, DANGER red #A52A2A on #FBE4E4, WARNING amber #92400E on #FDEBD3, INFO blue #1F4FB5 on #E1EBFC.
Never rely on color alone: pair every status with an icon and a label.

Type: Inter for UI text, JetBrains Mono for ids, hashes, code and tabular amounts. Display 40px bold, H1 30px bold,
H2 20px semibold, body 15px, small 13px, uppercase labels 11px with wide tracking.
Shape: 10px radius controls, 16px radius cards, fully round chips. Spacing scale 4, 8, 16, 24, 40.
Layout: content max width 1152px, 12 columns, 24px gutters. Buttons at least 44px tall.
Flat surfaces with a very soft shadow at most. Light theme only.
```

---

## 1. App concept (zoom out): the first prompt

```
Design a web app called "AgentEscrow": escrow and automatic arbitration for payments between AI agents, built on the PayPal sandbox.

The story: a Buyer agent posts a job with a bounty. PayPal HOLDS the money (authorizes it, does not charge it). A Worker agent
does the work. An automatic three-tier arbiter then verifies the work: (1) schema check, (2) hidden unit tests run in a sandbox,
(3) an AI judge scores quality. Only then does money move: PAID IN FULL, PARTIALLY PAID (pro-rated), or VOIDED (the buyer is
charged $0.00). The product's whole promise is that nobody has to trust anybody, and the money is never in doubt.

Screens: 1 Home, 2 Job board, 3 Post a job, 4 Job control room (the main screen), 5 Verdict receipt, 6 Operator console.
Users: a developer or founder who runs AI agents (buyer), an agent builder who earns from them (worker), and an operator.

Most important idea: on every screen, show the MONEY STATE first: not yet held, HELD in escrow, PAID OUT, or RELEASED
back to the buyer. Use the design system consistently. Create the Home screen first.
```

---

## 2. Screen prompts (zoom in): one prompt per screen

### S1. Home (landing)

```
Design the Home screen for AgentEscrow (desktop, 1440px wide).

Top app bar in deep ink #0B1F2A: shield logo mark + "AgentEscrow" on the left; links "Job board", "Post a job", "Operator";
on the right a small pill "PayPal sandbox" in teal. 

Hero, two columns. Left: small teal pill "Escrow for the agent economy", display headline "AI agents can hire each other. Now they
can pay each other safely.", a 20px muted sub-headline "AgentEscrow holds the money in PayPal, lets an autonomous arbiter verify
the work, and only then releases a payment: in full, in part, or not at all.", then a teal primary button "Run the guided demo →" and a
secondary outlined button "Browse the job board". Under them a 13px muted note "Uses the PayPal sandbox: no real money moves."
Right: a dark ink card titled "Three possible endings" with three rows, each with an icon in a colored circle: green check "Honest work: all hidden tests pass, paid in full";
gold scales "Partial work: 5 of 8 tests pass, a pro-rated payment"; red cross "Cheating work: caught before it runs, the buyer pays $0.00".

Below: section "How it works" with four equal cards (icon in an ink circle, number, title, one sentence): 1 Lock (PayPal authorizes the
bounty, money held not taken), 2 Work (worker starts only once funds are confirmed locked), 3 Verify (schema, hidden tests, AI judge),
4 Settle (full, partial or void). Below that: "Why you can trust the money flow" with a 2x2 grid of cards: "LLMs propose, code
disposes", "Signed spending mandates", "Settlement tickets", "Built to be attacked". Footer: centered muted line.
Generous whitespace, calm, no gradients, no stock photos.
```

### S2. Job board

```
Design the "Job board" screen (desktop).
Same app bar. Page title "Job board" with the subtitle "Every job is escrowed in PayPal before work starts." and a teal button "Post a job" on the right.
Under it, a row of filter pills: All (selected, ink), Open, In progress, Finished.
Then a responsive grid of 3 columns of job cards. Each card: title "Run-length encoding" (semibold), job id "job_7f3a91c2" in mono muted, a state chip
on the right, a 2-line muted description, and a footer row with the bounty "$5.00" bold, a clock icon with "in 23h 14m", and optionally a small
uppercase role tag such as "BUYER".
Show 6 cards with these states: Posted (neutral grey chip), Accepted (blue), Awaiting approval (amber), Escrow locked (gold chip with a lock icon),
Settled (green with check), Voided (red with cross). Cards have a 1px border and a teal border on hover.
Also design the empty state for the board: a dashed card, a document icon in a grey circle, the title "No jobs here yet", one muted sentence, and a teal button "Post the first job".
```

### S3. Post a job

```
Design the "Post a job" screen (desktop), a single centered card 672px wide under the page title "Post a job" with the subtitle
"Describe the work, set the bounty, and let escrow protect both sides."
Inside the card, top to bottom:
1) a grey info block: label "TASK TEMPLATE", "Run-length encoding (Python function)", muted explanation "You keep a hidden pytest suite the worker never sees, so the work is verified by facts, not opinions."
2) "Bounty (USD)" number input with value 5.00 and help text "Between $1 and $100 in this sandbox demo."
3) "Deadline for delivery" select with options 1 hour, 6 hours, 1 day (selected), 3 days, 7 days and help text "If nothing is delivered by then, the hold is released and you pay nothing."
4) a teal-tinted callout with a shield icon: "A signed spending mandate caps this escrow at $5.00. The payment server will refuse anything above it, whatever any agent asks for."
5) a full-width teal button "Post job".
Also show the invalid state of the bounty field (value 500): red border, red help text "Enter an amount between $1.00 and $100.00.", and the button disabled.
```

### S4. Job control room (the main screen)

```
Design the "Job control room" screen (desktop 1440px). This is the heart of the product: it answers "where is the money, and what happens next?".

Header: title "Run-length encoding" with a gold chip "Escrow locked" (lock icon); under it muted "Funds are held; the worker may start · bounty $5.00 · due in 23h 14m"
and the job id "job_7f3a91c2" in mono with a copy icon. On the right a segmented control "Acting as: Buyer | Worker".

Row 1: a full-width card with a horizontal 8-step progress tracker: Posted, Accepted, Funds pending, Escrow locked (current, filled ink),
Submitted, Arbitrating, Settling, Settled. Completed steps are teal with a check; upcoming steps are grey.

Row 2, two columns (main 1fr, right rail 360px sticky).
MAIN column cards: (a) "THE JOB": description, a mono function signature "def rle_encode(s: str) -> str", an acceptance criteria bullet list, and a collapsed
"Public example tests" disclosure with a dark code block. (b) "MONEY TIMELINE": a vertical live feed, each entry a small colored icon circle, a one-line message
and a mono "10:42:07 · paypal" caption. Sample entries: "Buyer posted job 'Run-length encoding' with a $5.00 bounty", "Signed spending mandate issued: escrow capped at $5.00",
"Worker 'codesmith-agent' committed to the task", "PayPal order SIM-ORDER-9F2C created (intent AUTHORIZE); waiting for buyer approval",
"PayPal authorization holds $5.00", "Escrow locked: funds are held, the worker may start".
RIGHT RAIL cards: (1) MONEY CARD with a gold border and gold-tinted background: chip "Held in escrow", the amount "$5.00" in 40px bold tabular numerals, "of a $5.00 bounty".
(2) "NEXT STEP" card: a labeled select "Which worker agent should take this job?" (Honest worker / Sloppy worker / Cheating worker), a teal full-width button "Run worker agent",
and a red outlined button "Cancel and release the hold". (3) "PAYPAL REFERENCES": Order, Authorization, each in mono with a copy icon.
Gold appears ONLY for held money. One teal button in the whole screen.
```

### S5. Job control room, after arbitration (verdict)

```
Design the lower part of the "Job control room" screen after the arbiter has decided (desktop). Replace the main column's content with an "ARBITER VERDICT" card:
1) A green banner with a check icon: "Paid in full" and the reason "V=0.97: all hidden tests passed", with "Captured $5.00 · worker $4.67 · fee $0.33".
2) Left: a semicircular score gauge reading 0.97 with tick markers at 0.50 and 0.85 labelled; right: a muted formula "V = 0.30 × schema + 0.40 × hidden tests + 0.30 × semantic judge. Any failed gate voids the hold, whatever the score."
3) Three equal tier cards: "Schema" (weight 30%, Passed, 1.00), "Hidden tests" (weight 40%, Passed, 1.00, "8 of 8 hidden tests passed in the docker sandbox"),
"Semantic judge" (weight 30%, Passed, 0.90, a one-sentence rationale).
4) A thin green strip with a shield icon: "Integrity gate passed".
Then design the failure variant of the same card: a red banner "Voided: the buyer was charged $0.00", gauge reading 0.30, the Hidden tests and Semantic judge cards in a grey "Not run" state
with "The code was never executed", and a red strip "Integrity gate failed: the code was never run" with a bullet "explanation: possible prompt injection (note-to-evaluator)".
The right rail's money card becomes red-tinted: "Released: buyer charged $0.00", "$0.00".
```

### S6. Verdict receipt

```
Design a printable "Verdict receipt" page (centered, 672px wide, document-like). 
Header band tinted teal #DDF3EF with a shield icon, small caps "AGENTESCROW VERDICT RECEIPT", a 30px green heading "Paid in full", and the line "Run-length encoding · job_7f3a91c2".
Body: one sentence reason "V=0.97: all hidden tests passed". A definition list with right-aligned tabular amounts: Bounty $5.00, Buyer charged $5.00, Worker paid $4.67,
Platform fee $0.33, Verification score 0.97, Hidden tests "8 of 8 passed", Integrity gate Passed.
Then "REFERENCES": rows with a muted label and a mono value with a copy icon: PayPal order, Authorization, Capture, Payout batch, Deliverable SHA-256, and a final divided row
"Signature (HMAC-SHA256)". Above the card, a text link "← Back to the job" and an outlined "Print receipt" button (hidden when printing).
Also design a variant with an amber banner "Simulated: no real PayPal calls were made and no money moved."
```

### S7. Operator console

```
Design the "Operator" screen (desktop). Title "Operator", subtitle "What needs attention, and where the money went.", right side outlined buttons "Close overdue jobs" and "Lock".
Row of 4 stat cards: Captured $15.00, Paid to workers $14.01, Platform fees $0.99, Jobs settled / voided "2 / 1" (tabular numerals).
Card "NEEDS ATTENTION (2)": a list where each row has the job title as a teal link, the job id in mono, an optional red error line
("capture_escrow failed: PayPal API error 422 ..."), a state chip (amber "Needs review", blue "Settling") and an outlined "Retry" button.
Card "ALL JOBS": a table with columns Job (mono id link), State (chip), Bounty, Worker ("codesmith-agent (worker@example.com)") with a muted uppercase header row.
Also design the locked state: a centered lock icon, "Operator access", the sentence "Enter the ADMIN_TOKEN configured on the server. It is kept in this browser only.", a password field and an ink "Unlock" button.
```

### S8. Mobile: Job control room

```
Design the "Job control room" for mobile (390px wide), single column. Order: header (title, gold "Escrow locked" chip, job id in mono);
the MONEY CARD first (gold: "Held in escrow", "$5.00"); then the "NEXT STEP" card with the persona select and a full-width 48px teal "Run worker agent" button;
then a VERTICAL progress tracker (8 steps, current one highlighted); then the Money timeline; then "The job". Sticky bottom bar is not needed.
All touch targets at least 44px. The app bar collapses the links into a menu button.
```

### S9. Feedback states

```
Design a small set of feedback components in the AgentEscrow style on one canvas:
1) an error banner: red container, alert icon, text "The buyer has not approved the PayPal order yet (status: CREATED)", a dismiss X;
2) a success banner: green container "PayPal confirmed the hold. The funds are locked in escrow.";
3) a warning banner: amber "You left PayPal without approving. Nothing was held; you can try again.";
4) an inline "working" row with a spinner: "The arbiter is checking the work…";
5) a full-page empty state "Job not found" (alert icon in a grey circle, one sentence, a teal text link "Back to the job board");
6) the "Your access to this job has expired" empty state with a lock icon and a button "Continue as a guest".
```

---

### S10. Post a job: template picker and custom task builder

```
Design the "Post a job" screen with a task chooser (desktop, centered 672px card). Top: the question "What should the worker build?" and a 2x2 grid of
selectable cards: "Run-length encoding", "Roman numerals to integer", "Balanced brackets" (each with a one-line summary and the function signature in mono),
and a fourth card "Your own task" with a code icon (selected, teal border and tint): "Write the description, tests and a reference solution. We check it in the sandbox first."
Below it, an expanded form "Define your task" with a "Load an example" outlined button: Title, Description (textarea), Function name and Signature side by side (mono), "Public example tests",
"Hidden tests (kept secret, committed by hash, published after the verdict)", "Reference solution (never shown to anyone; proves your tests are fair)" (all mono textareas),
then a full-width outlined button "Check the task in the sandbox".
Under the button a checklist of results, one row per check with an icon: green rows "Signature matches the function name", "Reference solution passes every hidden test (3/3 passed)",
"Hidden tests are deterministic (two runs agree)" and one RED row "Hidden tests reject a do-nothing stub: a stub that returns None passes 3 of 3 tests".
Then bounty, deadline, the teal mandate callout, and a disabled full-width button labelled "Check the task first".
Also design the all-green state with the line "The task passed every check. You can post it." and an enabled teal "Post job" button.
```

### S11. Receipt: audit panel

```
Extend the "Verdict receipt" page with a card titled "AUDIT THIS VERDICT" under the receipt. Text: "The receipt is signed with the platform's Ed25519 key (key id f817c8e8d6620fa4). Anyone can verify it
offline with scripts/verify_receipt.py." Three outlined buttons: "Verify signature", "Download receipt (JSON)", "Reveal hidden tests".
Show the results: a green banner "The signature is valid: this receipt is exactly what the platform issued." and a second green banner "These are the tests that were committed to before the work started
(your browser recomputed the SHA-256 and it matches)." followed by a dark code block with the revealed tests.
Also design the failure state: a red banner "The signature does NOT match: this receipt was altered." and one "These tests do NOT match the commitment."
In the receipt's REFERENCES list add the row "Hidden tests SHA-256 (committed at posting)" in mono with a copy icon.
```

### S12. For agents

```
Design a page "For agents" with the subtitle "AgentEscrow is a marketplace agents can use directly. No browser needed." (centered 768px column, three cards).
Card 1 "EARN MONEY WITH ANY MCP CLIENT": one paragraph and a divided list of seven tool names in mono with a muted one-line description each:
list_open_jobs, get_job_brief, accept_job, check_funding, submit_solution, get_result, withdraw; then a dark code block with the two commands that start the API and the marketplace server.
Card 2 "WHY A WORKER AGENT CAN TRUST THE PAYMENT": three bullets with teal icons (lock: funds held before work; scales: hidden tests committed by SHA-256; shield: Ed25519-signed receipts),
a code block showing the offline verify command, and two rows "Receipt signing key id" and "Public key (base64 Ed25519)" with mono values and copy icons.
Card 3 "DISCOVERY": one paragraph linking to /.well-known/agent-card.json that says it is a discovery card only.
```

## 3. Refinement prompts (use after any screen)

- `Increase text contrast on all muted text and make sure every status color meets WCAG AA on its container.`
- `Tighten the vertical spacing by about 20% and reduce card padding from 24px to 20px; keep the hierarchy.`
- `Replace the gold on this screen with the neutral grey: gold is reserved only for money held in escrow.`
- `Make the primary action more prominent and remove the second teal button; there should be one accent button per screen.`
- `Show the amounts with tabular numerals and right-align them in a column.`
- `Make the timeline entries denser (single line each) and add a subtle divider between them.`
- `Show this same screen in its loading state with skeleton blocks, and in its error state.`
- `Create the mobile version of this screen at 390px, stacking the right rail below the money card.`

## 4. What data each screen shows (so the design maps cleanly to the app)

| Stitch screen | React page / component | API fields it uses |
|---|---|---|
| S1 Home | `pages/HomePage.jsx` | `GET /api/health` (mode badge) |
| S2 Job board | `pages/JobBoardPage.jsx`, `components/JobCard.jsx` | `GET /api/jobs`: `job_id`, `state`, `contract.bounty_usd`, `contract.deadline_epoch`, `contract.specification.{title,description}` |
| S3 Post a job | `pages/CreateJobPage.jsx` | `POST /api/jobs` `{bounty_usd, deadline_hours}` |
| S4 Control room | `pages/JobPage.jsx`, `StateStepper`, `MoneyCard`, `MoneyTimeline`, `ActionPanel` | `GET /api/jobs/<id>`, `GET .../events`, SSE `.../stream` |
| S5 Verdict | `JobPage.jsx` → `OutcomeBanner`, `ScoreGauge`, `TierCards` | `verdict.{schema_check,integrity,sandbox,semantic,v_score}`, `decision.*` |
| S6 Receipt | `pages/ReceiptPage.jsx` | `GET /api/jobs/<id>/receipt` |
| S7 Operator | `pages/OpsPage.jsx` | `GET /api/admin/overview`, `GET /api/admin/jobs` |
| S8 Mobile | same components, responsive classes | same as S4 |
| S10 Task builder | `pages/CreateJobPage.jsx`, `components/LintReport.jsx` | `GET /api/templates`, `POST /api/tasks/validate` -> `{ok, checks[], ticket}` |
| S11 Receipt audit | `pages/ReceiptPage.jsx` (`Audit`) | `POST /api/receipts/verify`, `GET /api/jobs/<id>/hidden-tests` |
| S12 For agents | `pages/AgentsPage.jsx` | `GET /.well-known/agentescrow-receipt-key.json` |
| S9 Feedback | `ErrorBanner`, `EmptyState` in `components/ui.jsx` | n/a |
