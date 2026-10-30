import { AlertTriangle, Bot, ChevronDown, ChevronRight, Database, MessageSquare, Puzzle, Wrench } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { Span, Trace } from '../lib/api'
import { compact, ms, usd } from '../lib/format'
import { JsonView } from './JsonView'
import { Messages, OutputBlocks } from './Messages'
import { FloatingTip, TipRow } from './Tooltip'
import { KIND_COLOR } from './ui'

const KIND_ICON = { agent: Bot, llm: MessageSquare, tool: Wrench, retrieval: Database, custom: Puzzle }

interface Node {
  span: Span
  depth: number
  children: Node[]
}

function buildTree(spans: Span[]): Node[] {
  const sorted = [...spans].sort((a, b) => a.start_ns - b.start_ns)
  const byId = new Map<string, Node>()
  sorted.forEach((s) => byId.set(s.span_id, { span: s, depth: 0, children: [] }))
  const roots: Node[] = []
  for (const s of sorted) {
    const node = byId.get(s.span_id)!
    const parent = s.parent_id ? byId.get(s.parent_id) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  const setDepth = (n: Node, d: number) => {
    n.depth = d
    n.children.forEach((c) => setDepth(c, d + 1))
  }
  roots.forEach((r) => setDepth(r, 0))
  return roots
}

function flatten(nodes: Node[], collapsed: Set<string>, out: Node[] = []): Node[] {
  for (const n of nodes) {
    out.push(n)
    if (!collapsed.has(n.span.span_id)) flatten(n.children, collapsed, out)
  }
  return out
}

const dur = (s: Span) => (s.end_ns ? (s.end_ns - s.start_ns) / 1e6 : 0)

function niceTicks(totalMs: number): number[] {
  if (totalMs <= 0) return [0]
  const raw = totalMs / 4
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks = []
  for (let t = 0; t <= totalMs + 1e-9; t += step) ticks.push(t)
  return ticks
}

export function TraceView({ trace, divergeAt }: { trace: Trace; divergeAt?: number | null }) {
  const roots = useMemo(() => buildTree(trace.spans), [trace])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const rows = flatten(roots, collapsed)
  const [selectedId, setSelected] = useState<string | null>(
    () => trace.spans.find((s) => s.kind === 'llm')?.span_id ?? trace.spans[0]?.span_id ?? null,
  )
  const [hover, setHover] = useState<{ span: Span; x: number; y: number } | null>(null)
  const selected = trace.spans.find((s) => s.span_id === selectedId) ?? null

  const t0 = Math.min(...trace.spans.map((s) => s.start_ns))
  const t1 = Math.max(...trace.spans.map((s) => s.end_ns ?? s.start_ns))
  const total = Math.max((t1 - t0) / 1e6, 1e-6)
  const ticks = niceTicks(total)
  const toolOrder = trace.spans
    .filter((s) => s.kind === 'tool')
    .sort((a, b) => a.start_ns - b.start_ns)
    .map((s) => s.span_id)
  const kinds = [...new Set(trace.spans.map((s) => s.kind))]

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
      <div className="card min-w-0 overflow-hidden">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--border)] px-4 py-2 text-xs text-[var(--ink-2)]">
          {kinds.map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[k] }} />
              {k}
            </span>
          ))}
          <span className="ml-auto text-[var(--muted)] tnum">
            {trace.spans.length} spans · {ms(total)}
          </span>
        </div>
        <div className="grid grid-cols-[minmax(180px,38%)_1fr] text-[11px] text-[var(--muted)]">
          <div className="border-b border-[var(--border)] px-4 py-1.5">span</div>
          <div className="relative border-b border-[var(--border)]">
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-1.5 -translate-x-1/2 whitespace-nowrap tnum"
                style={{ left: `calc(${(t / total) * 100}% * 0.94 + 3%)` }}
              >
                {ms(t)}
              </span>
            ))}
            &nbsp;
          </div>
        </div>
        <div role="tree" className="max-h-[65vh] overflow-auto">
          {rows.map((n) => {
            const s = n.span
            const Icon = KIND_ICON[s.kind] ?? Puzzle
            const left = ((s.start_ns - t0) / 1e6 / total) * 100
            const width = Math.max((dur(s) / total) * 100, 0.3)
            const toolIndex = toolOrder.indexOf(s.span_id)
            const isDiverge = divergeAt != null && toolIndex === divergeAt
            const isSel = s.span_id === selectedId
            return (
              <div
                key={s.span_id}
                role="treeitem"
                aria-selected={isSel}
                tabIndex={0}
                onClick={() => setSelected(s.span_id)}
                onKeyDown={(e) => e.key === 'Enter' && setSelected(s.span_id)}
                className={`grid cursor-pointer grid-cols-[minmax(180px,38%)_1fr] items-center border-b border-[var(--border)]/50 text-sm outline-none transition-colors ${
                  isSel ? 'bg-[var(--surface-3)]' : 'hover:bg-[var(--surface-2)] focus-visible:bg-[var(--surface-2)]'
                }`}
              >
                <div className="flex min-w-0 items-center gap-1.5 py-1.5 pr-2" style={{ paddingLeft: 12 + n.depth * 16 }}>
                  {n.children.length ? (
                    <button
                      type="button"
                      aria-label={collapsed.has(s.span_id) ? 'expand' : 'collapse'}
                      className="text-[var(--muted)] hover:text-[var(--ink)]"
                      onClick={(e) => {
                        e.stopPropagation()
                        const next = new Set(collapsed)
                        if (next.has(s.span_id)) next.delete(s.span_id)
                        else next.add(s.span_id)
                        setCollapsed(next)
                      }}
                    >
                      {collapsed.has(s.span_id) ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                    </button>
                  ) : (
                    <span className="w-3.5" />
                  )}
                  <Icon size={14} style={{ color: KIND_COLOR[s.kind] }} className="shrink-0" />
                  <span className="truncate">{s.name}</span>
                  {s.status === 'error' && <AlertTriangle size={13} className="shrink-0 text-[var(--critical-ink)]" aria-label="error" />}
                  {isDiverge && (
                    <span className="shrink-0 rounded bg-[var(--critical)]/20 px-1.5 text-[10px] font-medium text-[var(--critical-ink)]">
                      diverges
                    </span>
                  )}
                </div>
                <div
                  className="relative h-7"
                  onPointerMove={(e) => setHover({ span: s, x: e.clientX, y: e.clientY })}
                  onPointerLeave={() => setHover(null)}
                >
                  {ticks.map((t) => (
                    <span key={t} className="absolute inset-y-0 w-px bg-[var(--grid)]" style={{ left: `calc(${(t / total) * 100}% * 0.94 + 3%)` }} />
                  ))}
                  <span
                    className="absolute top-1/2 h-3 -translate-y-1/2 rounded-[4px]"
                    style={{
                      left: `calc(${left}% * 0.94 + 3%)`,
                      width: `max(calc(${width}% * 0.94), 3px)`,
                      background: KIND_COLOR[s.kind],
                      opacity: s.kind === 'agent' ? 0.6 : 1,
                      outline: s.status === 'error' ? '2px solid var(--critical)' : undefined,
                    }}
                  />
                  {/* Duration sits after the bar, or before it when the bar reaches the right edge. */}
                  <span
                    className="pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap px-1.5 text-[11px] text-[var(--muted)] tnum"
                    style={
                      left + width <= 82
                        ? { left: `calc(${left + width}% * 0.94 + 3%)` }
                        : left > 15
                          ? { right: `calc(100% - (${left}% * 0.94 + 3%))` }
                          : { right: '3%', color: 'var(--ink)' }
                    }
                  >
                    {ms(dur(s))}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      {hover && (
        <FloatingTip x={hover.x} y={hover.y}>
          <div className="mb-1 font-medium text-[var(--ink)]">{hover.span.name}</div>
          <TipRow color={KIND_COLOR[hover.span.kind]} value={ms(dur(hover.span))} label={hover.span.kind} />
          <TipRow value={`+${ms((hover.span.start_ns - t0) / 1e6)}`} label="start" />
          {hover.span.input_tokens != null && (
            <TipRow
              value={`${compact(hover.span.input_tokens)} / ${compact(hover.span.output_tokens ?? 0)}`}
              label="tokens in / out"
            />
          )}
          {hover.span.cost_usd != null && <TipRow value={usd(hover.span.cost_usd)} label="cost" />}
        </FloatingTip>
      )}
      <SpanDetail span={selected} t0={t0} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-[var(--muted)]">{label}</div>
      <div className="text-sm tnum">{children}</div>
    </div>
  )
}

function SpanDetail({ span, t0 }: { span: Span | null; t0: number }) {
  const [tab, setTab] = useState<'io' | 'attributes'>('io')
  if (!span) return <div className="card p-4 text-sm text-[var(--ink-2)]">Select a span.</div>
  const input = span.input as { messages?: unknown; system?: unknown } | null
  return (
    <aside className="card flex max-h-[75vh] min-w-0 flex-col overflow-hidden lg:sticky lg:top-4">
      <div className="border-b border-[var(--border)] p-4">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND_COLOR[span.kind] }} />
          <span className="text-xs uppercase tracking-wide text-[var(--muted)]">{span.kind}</span>
        </div>
        <div className="mt-1 break-words font-medium">{span.name}</div>
        <div className="mt-3 grid grid-cols-3 gap-3">
          <Field label="duration">{ms(dur(span))}</Field>
          <Field label="start">+{ms((span.start_ns - t0) / 1e6)}</Field>
          <Field label="status">
            <span style={{ color: span.status === 'error' ? 'var(--critical-ink)' : undefined }}>{span.status}</span>
          </Field>
          {span.model && <Field label="model"><span className="break-all">{span.model}</span></Field>}
          {span.input_tokens != null && (
            <Field label="tokens in / out">
              {compact(span.input_tokens)} / {compact(span.output_tokens ?? 0)}
            </Field>
          )}
          {span.cost_usd != null && <Field label="cost">{usd(span.cost_usd)}</Field>}
        </div>
        {span.error && <div className="mt-3 rounded-md bg-[var(--critical)]/15 p-2 text-xs text-[var(--critical-ink)]">{span.error}</div>}
      </div>
      <div className="flex gap-4 border-b border-[var(--border)] px-4 text-sm">
        {(['io', 'attributes'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 py-2 ${tab === t ? 'border-[var(--accent)] text-[var(--ink)]' : 'border-transparent text-[var(--muted)] hover:text-[var(--ink)]'}`}
          >
            {t === 'io' ? 'input / output' : `attributes (${Object.keys(span.attributes).length})`}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {tab === 'io' ? (
          <>
            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
                {span.kind === 'llm' ? 'prompt' : span.kind === 'tool' ? 'arguments' : 'input'}
              </h3>
              {span.kind === 'llm' && input?.messages ? (
                <Messages messages={input.messages} system={input.system} />
              ) : (
                <JsonView value={span.input} />
              )}
            </section>
            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
                {span.kind === 'llm' ? 'response' : span.kind === 'tool' ? 'result' : 'output'}
              </h3>
              {span.kind === 'llm' ? <OutputBlocks output={span.output} /> : <JsonView value={span.output} />}
            </section>
          </>
        ) : (
          <JsonView value={span.attributes} />
        )}
      </div>
    </aside>
  )
}
