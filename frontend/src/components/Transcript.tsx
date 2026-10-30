import { Wrench } from 'lucide-react'
import type { Trace } from '../lib/api'
import { JsonView } from './JsonView'

/** The agent's trajectory as a reader would want it: what it said and which tools it called. */
export function Transcript({ trace }: { trace: Trace }) {
  const spans = [...trace.spans].sort((a, b) => a.start_ns - b.start_ns)
  const items: React.ReactNode[] = []
  spans.forEach((s) => {
    if (s.kind === 'llm') {
      const out = s.output as { content?: { type: string; text?: string }[] } | null
      for (const b of out?.content ?? [])
        if (b.type === 'text' && b.text)
          items.push(
            <div key={`${s.span_id}-t`} className="flex gap-2 text-sm">
              <span className="w-16 shrink-0 pt-0.5 text-right text-[11px] uppercase tracking-wide text-[var(--muted)]">agent</span>
              <div className="min-w-0 whitespace-pre-wrap">{b.text}</div>
            </div>,
          )
    } else if (s.kind === 'tool') {
      items.push(
        <div key={s.span_id} className="flex gap-2">
          <span className="w-16 shrink-0 pt-1 text-right text-[11px] uppercase tracking-wide text-[var(--muted)]">tool</span>
          <div className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-medium">
              <Wrench size={12} style={{ color: 'var(--series-2)' }} /> {s.name}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <div className="text-[10px] uppercase text-[var(--muted)]">args</div>
                <JsonView value={s.input} depth={1} />
              </div>
              <div>
                <div className="text-[10px] uppercase text-[var(--muted)]">result</div>
                <JsonView value={s.output} depth={1} />
              </div>
            </div>
          </div>
        </div>,
      )
    }
  })
  return <div className="space-y-3">{items.length ? items : <p className="text-sm text-[var(--muted)]">No LLM or tool spans.</p>}</div>
}
