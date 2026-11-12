// Small presentational building blocks. Styles come from the DESIGN.md tokens (see src/theme.css).
import { useState } from 'react'
import { Link } from 'react-router'
import Icon from './Icon.jsx'

export const TONES = {
  neutral: 'bg-surface-muted text-secondary',
  info: 'bg-info-container text-info',
  held: 'bg-held-container text-held',
  success: 'bg-success-container text-success',
  warning: 'bg-warning-container text-warning',
  danger: 'bg-danger-container text-danger',
}

export function Chip({ tone = 'neutral', icon, children, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-body-sm font-semibold ${TONES[tone]} ${className}`}>
      {icon && <Icon name={icon} className="h-3.5 w-3.5" />}
      {children}
    </span>
  )
}

const BUTTONS = {
  primary: 'bg-primary text-on-primary hover:opacity-90',
  accent: 'bg-tertiary text-on-tertiary hover:opacity-90',
  secondary: 'border border-border bg-surface text-text hover:bg-surface-muted',
  danger: 'border border-danger bg-surface text-danger hover:bg-danger-container',
}
const BUTTON_BASE =
  'inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 py-2 text-body-md font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'

export function Spinner({ className = 'h-4 w-4' }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${className}`} role="status" aria-label="Loading" />
}

export function Button({ variant = 'primary', busy = false, disabled, children, className = '', ...props }) {
  return (
    <button className={`${BUTTON_BASE} ${BUTTONS[variant]} ${className}`} disabled={disabled || busy} {...props}>
      {busy && <Spinner />}
      {children}
    </button>
  )
}

/** A link that looks like a button. Use `to` for in-app routes and `href` for external URLs. */
export function ButtonLink({ variant = 'primary', to, href, children, className = '', ...props }) {
  const classes = `${BUTTON_BASE} ${BUTTONS[variant]} ${className}`
  return to ? (
    <Link to={to} className={classes} {...props}>
      {children}
    </Link>
  ) : (
    <a href={href} className={classes} {...props}>
      {children}
    </a>
  )
}

const CARD_TONES = {
  default: 'border-border bg-surface text-text',
  dark: 'border-primary bg-primary text-on-primary',
}

export function Card({ title, action, children, className = '', tone = 'default' }) {
  return (
    <section className={`rounded-lg border p-6 shadow-[0_1px_2px_rgba(11,31,42,0.06)] ${CARD_TONES[tone]} ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className={`text-label-caps font-semibold uppercase tracking-label-caps ${tone === 'dark' ? 'opacity-70' : 'text-text-muted'}`}>{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function ErrorBanner({ error, onDismiss }) {
  if (!error) return null
  const message = error.message ?? String(error)
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger bg-danger-container p-3 text-body-sm text-danger">
      <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="flex-1">{message}</p>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss error" className="font-semibold">
          <Icon name="x" />
        </button>
      )}
    </div>
  )
}

export function EmptyState({ icon = 'doc', title, children, action }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-surface p-10 text-center">
      <span className="rounded-full bg-surface-muted p-3 text-secondary">
        <Icon name={icon} className="h-6 w-6" />
      </span>
      <h3 className="text-h3 font-semibold">{title}</h3>
      {children && <p className="max-w-[28rem] text-body-sm text-text-muted">{children}</p>}
      {action}
    </div>
  )
}

export function PageTitle({ title, subtitle, children }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-h1 font-bold">{title}</h1>
        {subtitle && <p className="mt-1 text-text-muted">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

/** An id or hash in mono with a copy button. */
export function MonoId({ value, label }) {
  const [copied, setCopied] = useState(false)
  if (!value) return null
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard can be unavailable (insecure context); the id is still selectable */
    }
  }
  return (
    <span className="inline-flex max-w-full items-center gap-1.5">
      <code className="truncate rounded bg-surface-muted px-1.5 py-0.5 font-mono text-mono" title={value}>
        {value}
      </code>
      <button onClick={copy} aria-label={`Copy ${label ?? 'id'}`} className="text-text-muted hover:text-text">
        <Icon name={copied ? 'check' : 'copy'} className="h-3.5 w-3.5" />
      </button>
    </span>
  )
}

/** An ordinary page: natural height, scrolls inside AppShell's <main>. */
export function Page({ children, className = '', narrow }) {
  return <div className={`py-6 sm:py-8 ${narrow ? `mx-auto ${narrow}` : ''} ${className}`}>{children}</div>
}

/**
 * A page with fixed regions. `top` stays put; below it `children` fill the rest of the screen on desktop (put
 * <Pane> columns in there and each scrolls on its own). On phones everything flows in one scroll, with `top` kept
 * pinned (sticky) so the title and state stay in view.
 */
export function Panes({ top, children, className = '' }) {
  return (
    <div className="flex min-h-full flex-col lg:h-full lg:min-h-0" data-panes>
      {top && <div className="sticky top-0 z-10 -mx-4 shrink-0 border-b border-border bg-neutral/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:static lg:mx-0 lg:border-0 lg:bg-transparent lg:px-0 lg:pb-4 lg:pt-6 lg:backdrop-blur-none">{top}</div>}
      <div className={`grid min-h-0 grid-cols-1 gap-6 pb-8 pt-4 lg:flex-1 lg:grid-rows-[minmax(0,1fr)] lg:pb-0 lg:pt-0 ${className}`}>{children}</div>
    </div>
  )
}

/** One column inside <Panes>: scrolls independently on desktop, flows normally on phones. */
export function Pane({ children, className = '' }) {
  return <div className={`min-h-0 min-w-0 lg:scroll-region lg:h-full lg:pb-8 lg:pr-1 ${className}`}>{children}</div>
}
