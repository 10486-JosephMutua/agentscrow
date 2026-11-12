import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { previewDocument } from '../lib/sitePreview.js'
import SiteChecklist from './SiteChecklist.jsx'
import SitePreview from './SitePreview.jsx'
import TierCards from './TierCards.jsx'
import { passingVerdict } from '../test/fixtures.js'

const HTML = '<!doctype html><html lang="en"><head><title>Acme</title></head><body><h1>Acme</h1></body></html>'

describe('previewDocument', () => {
  it('injects the policy first and keeps a single doctype', () => {
    const doc = previewDocument('<!DOCTYPE html><html><body>x</body></html>')
    expect(doc.startsWith('<!doctype html><meta http-equiv="Content-Security-Policy"')).toBe(true)
    expect(doc.toLowerCase().split('<!doctype').length - 1).toBe(1)
    expect(doc).toContain("default-src 'none'")
  })
})

describe('SitePreview', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => {
    delete URL.createObjectURL
    delete URL.revokeObjectURL
  })

  it('shows nothing until Run in browser is pressed, then runs the page in a locked-down frame', async () => {
    const user = userEvent.setup()
    render(<SitePreview html={HTML} title="Acme site" />)
    expect(screen.queryByTitle('Acme site')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /run in browser/i }))
    const frame = screen.getByTitle('Acme site')
    expect(frame).toHaveAttribute('sandbox', '') // no scripts, no forms, no same-origin
    expect(frame).toHaveAttribute('src', 'blob:preview')
    await user.click(screen.getByRole('button', { name: 'Phone' }))
    expect(frame.style.width).toBe('375px')
    await user.click(screen.getByRole('button', { name: /stop preview/i }))
    expect(screen.queryByTitle('Acme site')).not.toBeInTheDocument()
  })

  it('offers the page as a download', () => {
    render(<SitePreview html={HTML} />)
    expect(screen.getByRole('link', { name: /download index.html/i })).toHaveAttribute('download', 'index.html')
  })
})

describe('SiteChecklist', () => {
  const items = [
    { id: 'business_name', label: 'Business name is shown', source: 'preference', passed: true, detail: 'Found' },
    { id: 'contact_form', label: 'Contact form', source: 'preference', passed: false, detail: 'missing field(s): email' },
    { id: 'img_alt', label: 'Every image has alt text', source: 'baseline', passed: true, detail: '' },
  ]
  it('groups preferences and baseline checks and explains each failure', () => {
    render(<SiteChecklist items={items} />)
    expect(screen.getByText('2 of 3 checks were met.')).toBeInTheDocument()
    expect(within(screen.getByTestId('check-contact_form')).getByText(/missing field/)).toBeInTheDocument()
    expect(screen.getByText('What the buyer asked for')).toBeInTheDocument()
    expect(screen.getByText('Quality bar for every site')).toBeInTheDocument()
  })
  it('says so when everything was met', () => {
    render(<SiteChecklist items={items.map((item) => ({ ...item, passed: true }))} />)
    expect(screen.getByText('Every preference was met.')).toBeInTheDocument()
  })
})

describe('TierCards for a website job', () => {
  it('talks about preference checks and the tone judge', () => {
    const verdict = { ...passingVerdict, sandbox: { ...passingVerdict.sandbox, backend: 'html-checks', passed: 14, total: 14 } }
    render(<TierCards verdict={verdict} />)
    expect(within(screen.getByTestId('tier-Preference checks')).getByText(/14 of 14 preference checks were met/)).toBeInTheDocument()
    expect(screen.getByTestId('tier-Tone judge')).toBeInTheDocument()
  })
})
