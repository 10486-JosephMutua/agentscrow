---
version: alpha
name: AgentEscrow
description: A calm, high-trust "financial control room" for escrow between AI agents. Money state is always legible at a glance.
colors:
  primary: "#0B1F2A"
  on-primary: "#FFFFFF"
  secondary: "#41525C"
  tertiary: "#0B7A6B"
  on-tertiary: "#FFFFFF"
  tertiary-container: "#DDF3EF"
  neutral: "#F4F6F7"
  surface: "#FFFFFF"
  surface-muted: "#EAEFF1"
  border: "#D5DEE2"
  text: "#14232C"
  text-muted: "#5B6B74"
  held: "#8A5A0B"
  held-container: "#FBF1DC"
  success: "#146C3B"
  success-container: "#DFF4E7"
  warning: "#92400E"
  warning-container: "#FDEBD3"
  danger: "#A52A2A"
  danger-container: "#FBE4E4"
  info: "#1F4FB5"
  info-container: "#E1EBFC"
typography:
  display:
    fontFamily: Inter
    fontSize: 2.5rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: -0.02em
  h1:
    fontFamily: Inter
    fontSize: 1.875rem
    fontWeight: 700
    lineHeight: 1.2
  h2:
    fontFamily: Inter
    fontSize: 1.25rem
    fontWeight: 600
    lineHeight: 1.3
  h3:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: 600
    lineHeight: 1.4
  body-md:
    fontFamily: Inter
    fontSize: 0.9375rem
    fontWeight: 400
    lineHeight: 1.55
  body-sm:
    fontFamily: Inter
    fontSize: 0.8125rem
    fontWeight: 400
    lineHeight: 1.5
  label-caps:
    fontFamily: Inter
    fontSize: 0.6875rem
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0.08em
  mono:
    fontFamily: JetBrains Mono
    fontSize: 0.8125rem
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: 6px
  md: 10px
  lg: 16px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: 12px
  button-accent:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.on-tertiary}"
    rounded: "{rounded.md}"
    padding: 12px
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 24px
  page:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.text}"
  table-header:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label-caps}"
  chip-held:
    backgroundColor: "{colors.held-container}"
    textColor: "{colors.held}"
    rounded: "{rounded.full}"
    padding: 4px
  chip-success:
    backgroundColor: "{colors.success-container}"
    textColor: "{colors.success}"
    rounded: "{rounded.full}"
    padding: 4px
  chip-danger:
    backgroundColor: "{colors.danger-container}"
    textColor: "{colors.danger}"
    rounded: "{rounded.full}"
    padding: 4px
  chip-info:
    backgroundColor: "{colors.info-container}"
    textColor: "{colors.info}"
    rounded: "{rounded.full}"
    padding: 4px
  chip-warning:
    backgroundColor: "{colors.warning-container}"
    textColor: "{colors.warning}"
    rounded: "{rounded.full}"
    padding: 4px
---

## Overview

AgentEscrow is a financial control room for a new kind of customer: AI agents that hire other AI agents. The interface must feel like a trustworthy bank statement crossed with a mission-control console: **calm, precise, and honest about where the money is at every moment.** Nothing decorative, nothing playful with money. Emphasis comes from clear hierarchy and a small set of status colors, never from ornament.

The single most important idea in every screen is the **money state**: is the buyer's money *not yet held*, *held in escrow*, *paid out*, or *released back*? Every layout answers that first.

## Colors

The palette is a deep ink neutral foundation with one accent and a strict status vocabulary.

- **Primary (#0B1F2A):** Ledger ink for the app bar, headings and primary actions.
- **Tertiary (#0B7A6B):** Escrow teal (#0B7A6B), the single brand accent. Used for the main call to action and "verified" moments.
- **Held (#8A5A0B, container #FBF1DC):** Vault gold. Reserved *only* for money currently locked in escrow. Never use it for anything else.
- **Success (#146C3B):** Funds paid out / tests passed. **Danger (#A52A2A):** voided, failed, rejected. **Warning (#92400E):** needs a human. **Info (#1F4FB5):** work in progress.
- **Neutral (#F4F6F7)** is the page background; **Surface (#FFFFFF)** is for cards. Text is #14232C, secondary text #5B6B74.

Every status is conveyed by color **and** an icon or label, never color alone.

## Typography

Inter for everything people read; JetBrains Mono for anything a machine produced: job ids, PayPal ids, code, amounts in tables. Amounts use tabular numerals so columns align. Headings are tight and bold; body text is 15px with generous line height. Small uppercase labels (11px, wide tracking) title card sections.

## Layout

A 12-column grid, content max width 1152px, 24px page gutters (16px on mobile). Spacing follows a 4/8/16/24/40 scale. The job screen uses a two-column layout on desktop (main flow left, 360px sticky "money and actions" rail right) and stacks on mobile with the money summary first.

## Elevation & Depth

Flat by default. Cards have a 1px border (#D5DEE2) and, at most, a very soft shadow (0 1px 2px rgba(11,31,42,0.06)). Modals and menus may use a larger soft shadow. No gradients except a subtle teal tint on the verified receipt.

## Shapes

Rounded rectangles: 10px for controls, 16px for cards, fully round for chips and avatars. Progress and score gauges use round caps.

## Components

- **Buttons:** primary (ink), accent (teal, one per screen), secondary (outlined), danger (outlined red). 44px minimum touch height. Disabled buttons explain *why* in adjacent text.
- **State chips:** pill-shaped, icon + label, using the status color pairs (held gold, success green, danger red, info blue, warning orange).
- **State stepper:** horizontal on desktop, vertical on mobile: Posted, Accepted, Funds pending, Escrow locked, Submitted, Arbitrating, Settling, Settled or Voided. The current step is filled; completed steps show a check.
- **Money timeline:** a vertical feed of events with a time, an icon by kind (state, PayPal, tier, decision, error) and a one-line message; PayPal ids in mono and copyable.
- **Tier cards:** three equal cards (Schema, Hidden tests, Semantic judge) plus an integrity gate strip, each with a score and pass/fail state.
- **Score gauge:** semicircle gauge from 0 to 1 with markers at 0.50 and 0.85.
- **Receipt:** a printable, document-like card with a subtle teal header, a signature block and copyable ids.

## Do's and Don'ts

- Do show the amount and its state (held, paid, released) together, always.
- Do give every empty state one clear next action.
- Do keep one accent button per screen.
- Don't use gold for anything but held funds.
- Don't use red for anything but failure, void, or refusal.
- Don't hide ids: show them in mono with a copy button.
- Don't rely on color alone for meaning.
