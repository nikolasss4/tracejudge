import { useState } from 'react'

/** Readable rendering of arbitrary JSON values: strings as text, objects as collapsible trees. */
export function JsonView({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null || value === undefined) return <span className="text-[var(--muted)]">null</span>
  if (typeof value === 'string')
    return depth === 0 ? (
      <div className="whitespace-pre-wrap break-words text-[var(--ink)]">{value}</div>
    ) : (
      <span className="whitespace-pre-wrap break-words text-[var(--series-3)]">"{value}"</span>
    )
  if (typeof value === 'number' || typeof value === 'boolean')
    return <span className="text-[var(--series-1)]">{String(value)}</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-[var(--muted)]">[]</span>
    return <Collapsible open={depth < 3} label={`[${value.length}]`}>
      {value.map((v, i) => (
        <div key={i} className="flex gap-2">
          <span className="select-none text-[var(--muted)]">{i}</span>
          <div className="min-w-0 flex-1"><JsonView value={v} depth={depth + 1} /></div>
        </div>
      ))}
    </Collapsible>
  }
  const entries = Object.entries(value as Record<string, unknown>)
  if (entries.length === 0) return <span className="text-[var(--muted)]">{'{}'}</span>
  return (
    <Collapsible open={depth < 3} label={`{${entries.length}}`}>
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="shrink-0 text-[var(--ink-2)]">{k}:</span>
          <div className="min-w-0 flex-1"><JsonView value={v} depth={depth + 1} /></div>
        </div>
      ))}
    </Collapsible>
  )
}

function Collapsible({ open, label, children }: { open: boolean; label: string; children: React.ReactNode }) {
  const [isOpen, setOpen] = useState(open)
  return (
    <div className="font-mono text-xs leading-relaxed">
      <button type="button" className="text-[var(--muted)] hover:text-[var(--ink)]" onClick={() => setOpen(!isOpen)}>
        {isOpen ? '▾' : '▸'} {label}
      </button>
      {isOpen && <div className="border-l border-[var(--grid)] pl-3">{children}</div>}
    </div>
  )
}
