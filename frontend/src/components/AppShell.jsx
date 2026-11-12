import { NavLink, Outlet, useLocation } from 'react-router'
import { useEffect, useRef, useState } from 'react'
import { getHealth } from '../api/client.js'
import { useLedger } from '../hooks/useLedger.js'
import { formatUsd } from '../lib/format.js'
import Icon from './Icon.jsx'

const LINKS = [
  { to: '/', label: 'Home', end: true },
  { to: '/jobs', label: 'Job board' },
  { to: '/new', label: 'Post a job' },
  { to: '/agents', label: 'For agents' },
  { to: '/ops', label: 'Operator' },
]

function ModeBadge({ health, className = '' }) {
  if (!health) return null
  const simulated = health.paypal_mode === 'simulated'
  return (
    <span
      className={`items-center gap-1.5 rounded-full px-2.5 py-1 text-label-caps font-semibold uppercase tracking-label-caps ${simulated ? 'bg-warning-container text-warning' : 'bg-tertiary-container text-tertiary'} ${className}`}
      title={simulated ? 'No real PayPal calls are made' : 'Connected to the PayPal sandbox'}
    >
      {simulated ? 'Simulated PayPal' : 'PayPal sandbox'}
    </span>
  )
}

function LedgerPills({ ledger }) {
  if (!ledger.loaded) return null
  return (
    <div className="hidden items-center gap-2 font-mono text-mono md:flex" aria-label="Escrow totals">
      <span className="flex items-center gap-1.5 rounded-full bg-held-container px-2.5 py-1 text-held">
        <span className="h-1.5 w-1.5 rounded-full bg-held" />
        <span className="text-label-caps font-semibold uppercase tracking-label-caps">Held</span>
        <b className="tabular">{formatUsd(ledger.held)}</b>
      </span>
      <span className="hidden items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-on-primary lg:flex">
        <span className="text-label-caps font-semibold uppercase tracking-label-caps opacity-70">Paid out</span>
        <b className="tabular">{formatUsd(ledger.paid)}</b>
      </span>
    </div>
  )
}

const navClass = ({ isActive }) =>
  `whitespace-nowrap rounded-md px-3 py-2 text-body-sm font-semibold transition ${isActive ? 'bg-white/15' : 'hover:bg-white/10'}`

export default function AppShell() {
  const [health, setHealth] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const ledger = useLedger()
  const scroller = useRef(null)
  const { pathname } = useLocation()

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  // A new page starts at the top of the scrolling region, and the mobile menu closes.
  useEffect(() => {
    setMenuOpen(false)
    scroller.current?.scrollTo?.(0, 0)
  }, [pathname])

  useEffect(() => {
    if (!menuOpen) return undefined
    const onKey = (event) => event.key === 'Escape' && setMenuOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {/* Fixed chrome: never scrolls. */}
      <header className="pt-safe z-30 shrink-0 bg-primary text-on-primary shadow-[0_1px_8px_rgba(11,31,42,0.2)]">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:h-16 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2 text-h3 font-bold">
            <Icon name="shield" className="h-6 w-6 text-tertiary-container" />
            AgentEscrow
          </NavLink>
          <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
            {LINKS.slice(1).map((link) => (
              <NavLink key={link.to} to={link.to} className={navClass}>
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <LedgerPills ledger={ledger} />
            <ModeBadge health={health} className="hidden sm:inline-flex" />
            <button
              type="button"
              className="flex h-11 w-11 items-center justify-center rounded-md hover:bg-white/10 md:hidden"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <Icon name={menuOpen ? 'x' : 'menu'} className="h-6 w-6" />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile menu: a drawer over the content, with its own scroll lock via the scrim. */}
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="presentation">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-primary/50 backdrop-blur-sm" onClick={() => setMenuOpen(false)} />
          <aside id="mobile-menu" className="pt-safe pb-safe absolute inset-y-0 right-0 flex w-[min(20rem,85vw)] flex-col bg-surface shadow-xl">
            <div className="flex h-14 items-center justify-between bg-primary px-4 text-on-primary">
              <span className="font-semibold">Menu</span>
              <button type="button" aria-label="Close menu" className="flex h-11 w-11 items-center justify-center rounded-md hover:bg-white/10" onClick={() => setMenuOpen(false)}>
                <Icon name="x" className="h-5 w-5" />
              </button>
            </div>
            <nav className="scroll-region flex-1 space-y-1 p-3" aria-label="Mobile">
              {LINKS.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) => `flex min-h-11 items-center rounded-md px-3 text-body-md font-semibold ${isActive ? 'bg-primary text-on-primary' : 'text-text hover:bg-surface-muted'}`}
                >
                  {link.label}
                </NavLink>
              ))}
            </nav>
            <div className="space-y-2 border-t border-border bg-surface-muted p-4 text-body-sm">
              {ledger.loaded && (
                <dl className="tabular grid grid-cols-2 gap-y-1">
                  <dt className="text-text-muted">Held in escrow</dt>
                  <dd className="text-right font-semibold">{formatUsd(ledger.held)}</dd>
                  <dt className="text-text-muted">Paid out</dt>
                  <dd className="text-right font-semibold">{formatUsd(ledger.paid)}</dd>
                </dl>
              )}
              <p className="text-text-muted">{health?.paypal_mode === 'simulated' ? 'Simulated PayPal: no real calls are made.' : 'PayPal sandbox: no real money moves.'}</p>
            </div>
          </aside>
        </div>
      )}

      {/* The one scrolling region. Ordinary pages are wrapped in <Page> (padding, natural height); pages with fixed panes use <Panes> and fill it (h-full), scrolling their own columns. */}
      <main ref={scroller} className="scroll-region min-h-0 flex-1">
        <div className="mx-auto h-full w-full max-w-6xl px-4 sm:px-6">
          <Outlet context={{ health, ledger }} />
        </div>
      </main>

      <footer className="hidden shrink-0 border-t border-border bg-surface px-6 py-2 text-center text-body-sm text-text-muted sm:block">
        AgentEscrow · built for the PayPal "Build What's Next" hackathon · sandbox money only
      </footer>
    </div>
  )
}
