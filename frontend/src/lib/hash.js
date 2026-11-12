/** SHA-256 of a string as lowercase hex, computed in the browser (Web Crypto). Returns '' where Web Crypto is unavailable. */
export async function sha256Hex(text) {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) return ''
  const digest = await subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}
