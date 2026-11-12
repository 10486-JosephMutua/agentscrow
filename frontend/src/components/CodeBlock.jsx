/** Read-only code. Never executed or rendered as HTML: React escapes it. */
export default function CodeBlock({ code, label }) {
  return (
    <pre className="scroll-region max-h-96 overflow-x-auto rounded-md bg-primary p-4 font-mono text-mono leading-relaxed text-on-primary" aria-label={label}>
      <code>{code}</code>
    </pre>
  )
}
