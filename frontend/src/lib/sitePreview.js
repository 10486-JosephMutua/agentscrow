// Wraps a worker's website for the preview frame. The worker's page is UNTRUSTED, so it runs in an iframe with an empty
// `sandbox` attribute (no scripts, no forms, no same-origin access) and this Content-Security-Policy as a second layer:
// nothing can load from the network and no script can run, even if one slipped past the server's integrity gate.
export const PREVIEW_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'"

/** The page with the policy injected first (after stripping its own doctype so the frame stays in standards mode). */
export function previewDocument(html) {
  const body = String(html ?? '').replace(/^\s*<!doctype[^>]*>/i, '')
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">${body}`
}

/** Object URL for a piece of HTML, or null where the browser (or a test environment) cannot make one. */
export function htmlObjectUrl(html) {
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') return null
  return URL.createObjectURL(new Blob([html], { type: 'text/html' }))
}

export function revokeObjectUrl(url) {
  if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(url)
}
