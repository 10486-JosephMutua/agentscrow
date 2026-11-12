# From Stitch to the React app

The app in `frontend/` is complete and already styled with the tokens from `DESIGN.md`. Stitch is how you get a
more polished visual pass. This guide shows how to bring a Stitch design into the app **without breaking behavior**.

## The workflow

1. **Design system.** Import `DESIGN.md` into your Stitch project (or paste the design-system prompt from `PROMPTS.md`).
2. **Generate.** Paste the prompts in `PROMPTS.md` in order (app concept first, then one screen at a time).
3. **Review against the checks below**, using the refinement prompts for anything off.
4. **Export** each screen's HTML (Tailwind) from Stitch.
5. **Port** it into the matching component (table in `PROMPTS.md`, section 4), following the checklist.
6. **Verify:** `cd frontend && npm test && npm run build`, then run the smoke test (`npm run smoke`).

If you edit `DESIGN.md`, regenerate the Tailwind theme with `cd frontend && npm run theme`, and lint it with
`npx @google/design.md lint ../docs/stitch/DESIGN.md` (the current file has zero errors and one benign warning:
the `border` color has no component property to reference it).

## Where behavior lives (do not paste over it)

Each page is a *container* (data, state, API calls) around *presentational* components (markup only). Port Stitch's
markup into the presentational parts and keep the containers:

| Keep (logic) | Replace (markup) |
|---|---|
| `src/hooks/useJob.js` (loading, SSE, polling) | `components/StateStepper.jsx`, `MoneyCard.jsx`, `MoneyTimeline.jsx` |
| `src/api/*` (client, tokens) | `components/TierCards.jsx`, `ScoreGauge.jsx`, `OutcomeBanner.jsx` |
| `components/ActionPanel.jsx` handlers (`useAsyncAction`) | the JSX *around* those handlers |
| `pages/*` data loading | page layout wrappers |

## Porting checklist (HTML from Stitch to JSX)

- `class` to `className`, `for` to `htmlFor`, `tabindex` to `tabIndex`, `stroke-width` to `strokeWidth`, and so on for SVG attributes.
- Close void tags (`<img />`, `<input />`, `<br />`). Convert `style="..."` to an object, and `<!-- -->` to `{/* */}`.
- **Replace static text with props**: job title, amounts, ids, chips and timeline entries come from the `job` and `events` data.
  Use the helpers in `src/lib/format.js` and `src/lib/states.js` instead of hard-coding "Escrow locked" or "$5.00".
- **Keep the semantics**: `role`, `aria-*`, `aria-live` on the timeline and money card, `aria-current="step"` on the stepper,
  labels tied to inputs. The component tests check several of them and will tell you what you dropped.
- Keep tooltips/ids/test hooks: `data-testid` attributes (`money-amount`, `outcome-banner`, `integrity-strip`, `tier-*`) are used by tests.
- Buttons that call the API stay `<Button>` / `<ButtonLink>` from `components/ui.jsx`; restyle them there once and every screen follows.

## Things in a Stitch export that will not work here (and the fix)

| In the export | Why it is a problem | Fix |
|---|---|---|
| `<script src="https://cdn.tailwindcss.com">` or an inline `tailwind.config` | The server's Content-Security-Policy only allows scripts from the same origin; Tailwind is already compiled by Vite | Delete the script. Move any custom colors into `DESIGN.md` (then `npm run theme`) instead of a runtime config |
| Google Fonts / Material Symbols links | Blocked by CSP (`font-src 'self'`, `style-src 'self'`) and a network dependency | Use the font stacks already in `index.css`, or self-host the fonts and add them under `public/`. The built-in icon set is `components/Icon.jsx` |
| Remote images / avatars | Blocked by CSP (`img-src 'self' data:`) and not needed | Remove them. This product has no photography by design |
| Brand logos (PayPal, others) | The hackathon forbids third-party trademarks in the demo video | Keep the neutral shield mark; write "PayPal sandbox" in text only |
| Hard-coded hex colors | They drift from the design system | Replace with token classes (`bg-tertiary`, `text-text-muted`, `bg-held-container`, ...) |

## Quick design review checklist

- The money state (held / paid / released) is the first thing on every job screen.
- Gold is used **only** for money held in escrow; red only for failure, void or refusal.
- One teal accent button per screen. Every status has an icon or label, never color alone.
- Text and status colors keep WCAG AA contrast (the design system was linted for this).
- It works at 390px wide (the stepper turns vertical) and prints cleanly (receipt page).
