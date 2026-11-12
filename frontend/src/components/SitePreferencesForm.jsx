import { useEffect, useState } from 'react'
import * as api from '../api/client.js'
import { Button } from './ui.jsx'

const INPUT = 'min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-body-md'

export const DEFAULT_SITE = {
  business_name: '',
  purpose: '',
  sections: ['hero', 'about', 'contact'],
  primary_color: 'blue',
  theme: 'any',
  contact_fields: ['name', 'email', 'message'],
  include_text: [],
  tone: 'Minimal and professional',
}

export const EXAMPLE_SITE = {
  business_name: 'Lens & Light Studio',
  purpose: 'Portfolio website for a wedding and portrait photographer',
  sections: ['hero', 'about', 'gallery', 'pricing', 'contact'],
  primary_color: 'blue',
  theme: 'dark',
  contact_fields: ['name', 'email', 'message'],
  include_text: ['Book a free consultation'],
  tone: 'Minimal and professional',
}

/** True when the form has what the server needs; the server validates everything again. */
export function siteIsValid(site) {
  return site.business_name.trim().length >= 2 && site.purpose.trim().length >= 5 && site.sections.length >= 1
}

function toggle(list, id) {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id]
}

function Pills({ legend, options, selected, onToggle, note }) {
  return (
    <fieldset>
      <legend className="mb-2 text-body-sm font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const on = selected.includes(option.id)
          return (
            <label key={option.id} className={`cursor-pointer rounded-full border px-3 py-1.5 text-body-sm font-semibold ${on ? 'border-tertiary bg-tertiary-container text-tertiary' : 'border-border bg-surface hover:bg-surface-muted'}`}>
              <input type="checkbox" className="sr-only" checked={on} onChange={() => onToggle(option.id)} />
              {on ? '✓ ' : ''}{option.label}
            </label>
          )
        })}
      </div>
      {note && <p className="mt-1 text-body-sm text-text-muted">{note}</p>}
    </fieldset>
  )
}

/**
 * The buyer's preference form. Every answer becomes a check the delivered website is held to, so each control says
 * what will be checked.
 */
export default function SitePreferencesForm({ value, onChange }) {
  const [options, setOptions] = useState(null)
  const [phrases, setPhrases] = useState(value.include_text.join('\n'))
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    api.getSiteOptions().then(setOptions).catch(setLoadError)
  }, [])

  const set = (patch) => onChange({ ...value, ...patch })
  const loadExample = () => {
    setPhrases(EXAMPLE_SITE.include_text.join('\n'))
    onChange(EXAMPLE_SITE)
  }

  if (loadError) return <p className="text-body-sm text-danger">Could not load the form options: {loadError.message}</p>
  if (!options) return <p className="text-body-sm text-text-muted">Loading the preference form…</p>

  return (
    <div className="space-y-5 rounded-lg border border-border p-4" data-testid="site-form">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-h3 font-semibold">What should the website be like?</h2>
        <Button variant="secondary" type="button" onClick={loadExample}>Load an example</Button>
      </div>

      <div>
        <label htmlFor="s-name" className="mb-1 block text-body-sm font-semibold">Business name <span className="font-normal text-text-muted">(checked in the page title and the text)</span></label>
        <input id="s-name" className={INPUT} value={value.business_name} maxLength={60} onChange={(event) => set({ business_name: event.target.value })} />
      </div>
      <div>
        <label htmlFor="s-purpose" className="mb-1 block text-body-sm font-semibold">What is the website for?</label>
        <input id="s-purpose" className={INPUT} value={value.purpose} maxLength={200} onChange={(event) => set({ purpose: event.target.value })} placeholder="e.g. Portfolio for a wedding photographer" />
      </div>

      <Pills legend="Sections (each one must exist on the page)" options={options.sections} selected={value.sections} onToggle={(id) => set({ sections: toggle(value.sections, id) })} />

      <fieldset>
        <legend className="mb-2 text-body-sm font-semibold">Main accent colour <span className="font-normal text-text-muted">(must be the dominant colour in the CSS)</span></legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Accent colour">
          {options.colors.map((color) => (
            <label key={color.id} className={`flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-body-sm font-semibold ${value.primary_color === color.id ? 'border-tertiary bg-tertiary-container' : 'border-border bg-surface hover:bg-surface-muted'}`}>
              <input type="radio" name="s-color" className="sr-only" checked={value.primary_color === color.id} onChange={() => set({ primary_color: color.id })} />
              <span className="inline-block h-4 w-4 rounded-full border border-border" style={{ background: color.hex }} aria-hidden="true" />
              {color.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-body-sm font-semibold">Page background</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Page background">
          {options.themes.map((theme) => (
            <label key={theme} className={`cursor-pointer rounded-full border px-3 py-1.5 text-body-sm font-semibold ${value.theme === theme ? 'border-tertiary bg-tertiary-container' : 'border-border bg-surface hover:bg-surface-muted'}`}>
              <input type="radio" name="s-theme" className="sr-only" checked={value.theme === theme} onChange={() => set({ theme })} />
              {theme === 'any' ? 'No preference' : theme === 'light' ? 'Light' : 'Dark'}
            </label>
          ))}
        </div>
      </fieldset>

      <Pills
        legend="Contact form fields"
        options={options.contact_fields}
        selected={value.contact_fields}
        onToggle={(id) => set({ contact_fields: toggle(value.contact_fields, id) })}
        note="Each chosen field must be present and labelled, with a submit button. Choosing any adds the Contact section."
      />

      <div>
        <label htmlFor="s-phrases" className="mb-1 block text-body-sm font-semibold">Text that must appear <span className="font-normal text-text-muted">(one phrase per line, up to {options.limits.max_phrases})</span></label>
        <textarea
          id="s-phrases"
          className={INPUT}
          rows={2}
          value={phrases}
          onChange={(event) => {
            setPhrases(event.target.value)
            set({ include_text: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, options.limits.max_phrases) })
          }}
          placeholder="e.g. Book a free consultation"
        />
      </div>

      <div>
        <label htmlFor="s-tone" className="mb-1 block text-body-sm font-semibold">Tone <span className="font-normal text-text-muted">(the only preference scored by the AI judge; leave empty to skip)</span></label>
        <input id="s-tone" className={INPUT} list="s-tone-presets" value={value.tone ?? ''} maxLength={80} onChange={(event) => set({ tone: event.target.value })} />
        <datalist id="s-tone-presets">
          {options.tones.map((tone) => (
            <option key={tone} value={tone} />
          ))}
        </datalist>
      </div>
    </div>
  )
}
