import { useEffect, useMemo, useState } from 'react'
import { htmlObjectUrl, previewDocument, revokeObjectUrl } from '../lib/sitePreview.js'
import Icon from './Icon.jsx'
import { Button } from './ui.jsx'

const WIDTHS = [
  { id: 'phone', label: 'Phone', width: '375px' },
  { id: 'tablet', label: 'Tablet', width: '768px' },
  { id: 'desktop', label: 'Desktop', width: '100%' },
]

/**
 * Run the worker's website right here in the browser.
 *
 * Nothing runs until the person presses "Run in browser". The page is shown in a locked-down frame (no scripts, no
 * network; see lib/sitePreview.js). It is loaded from an object URL rather than `srcdoc` so that in-page links such as
 * href="#gallery" scroll inside the frame instead of trying to navigate it to this app.
 */
export default function SitePreview({ html, title = 'Website preview' }) {
  const [running, setRunning] = useState(false)
  const [width, setWidth] = useState('100%')
  const [fullscreen, setFullscreen] = useState(false)
  const doc = useMemo(() => previewDocument(html), [html])
  const [frameUrl, setFrameUrl] = useState(null)
  const [downloadUrl, setDownloadUrl] = useState(null)

  useEffect(() => {
    if (!running) return undefined
    const url = htmlObjectUrl(doc)
    setFrameUrl(url)
    return () => {
      revokeObjectUrl(url)
      setFrameUrl(null)
    }
  }, [running, doc])

  useEffect(() => {
    const url = htmlObjectUrl(html)
    setDownloadUrl(url)
    return () => revokeObjectUrl(url)
  }, [html])

  return (
    <div className={fullscreen ? 'fixed inset-0 z-50 flex flex-col gap-3 overflow-auto bg-surface p-4' : 'space-y-3'} data-testid="site-preview">
      <div className="flex flex-wrap items-center gap-2">
        {running ? (
          <Button variant="secondary" onClick={() => setRunning(false)}>Stop preview</Button>
        ) : (
          <Button variant="accent" onClick={() => setRunning(true)}>
            <Icon name="arrow" /> Run in browser
          </Button>
        )}
        {running && (
          <div className="inline-flex rounded-full border border-border bg-surface p-1" role="group" aria-label="Preview width">
            {WIDTHS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={width === item.width}
                onClick={() => setWidth(item.width)}
                className={`rounded-full px-3 py-1 text-body-sm font-semibold ${width === item.width ? 'bg-primary text-on-primary' : 'text-text-muted hover:text-text'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
        {running && (
          <Button variant="secondary" onClick={() => setFullscreen((value) => !value)}>
            {fullscreen ? 'Exit full screen' : 'Full screen'}
          </Button>
        )}
        {downloadUrl && (
          <a href={downloadUrl} download="index.html" className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface px-4 py-2 text-body-md font-semibold hover:bg-surface-muted">
            <Icon name="download" /> Download index.html
          </a>
        )}
      </div>

      {running ? (
        frameUrl ? (
          <iframe
            title={title}
            src={frameUrl}
            sandbox=""
            style={{ width, height: fullscreen ? '100%' : '560px' }}
            className="mx-auto block min-h-[320px] max-w-full flex-1 rounded-md border border-border bg-white"
          />
        ) : (
          <p className="text-body-sm text-text-muted">This browser cannot preview the page here. Use &ldquo;Download index.html&rdquo; and open it yourself.</p>
        )
      ) : (
        <div className="grid h-40 place-items-center rounded-md border-2 border-dashed border-border p-4 text-center text-body-sm text-text-muted">
          Press &ldquo;Run in browser&rdquo; to see the website exactly as the worker delivered it.
        </div>
      )}
      <p className="text-body-sm text-text-muted">The page runs in a locked-down frame: no scripts, no network, no access to this app.</p>
    </div>
  )
}
