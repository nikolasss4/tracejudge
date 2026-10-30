import { Wrench } from 'lucide-react'
import { JsonView } from './JsonView'

type Block = { type?: string; text?: string; name?: string; input?: unknown; content?: unknown; tool_use_id?: string }

function blocksOf(content: unknown): Block[] {
  if (typeof content === 'string') return [{ type: 'text', text: content }]
  if (Array.isArray(content)) return content as Block[]
  return [{ type: 'json', content }]
}

function BlockView({ b }: { b: Block }) {
  if (b.type === 'text') return <div className="whitespace-pre-wrap break-words">{b.text}</div>
  if (b.type === 'tool_use' || b.type === 'tool_call')
    return (
      <div className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2">
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-[var(--ink-2)]">
          <Wrench size={12} style={{ color: 'var(--series-2)' }} /> {b.name}
        </div>
        <JsonView value={b.input ?? (b as Record<string, unknown>).arguments} depth={1} />
      </div>
    )
  if (b.type === 'tool_result') {
    let parsed: unknown = b.content
    if (typeof parsed === 'string') {
      try { parsed = JSON.parse(parsed) } catch { /* plain text result */ }
    }
    return (
      <div className="rounded-md border border-dashed border-[var(--border)] p-2">
        <div className="mb-1 text-xs text-[var(--muted)]">tool result</div>
        <JsonView value={parsed} depth={1} />
      </div>
    )
  }
  if (b.type === 'thinking') return <div className="text-xs italic text-[var(--muted)]">(thinking)</div>
  return <JsonView value={b.content ?? b} depth={1} />
}

/** Chat-style rendering of an LLM span's messages (Anthropic and OpenAI-ish shapes). */
export function Messages({ messages, system }: { messages: unknown; system?: unknown }) {
  if (!Array.isArray(messages)) return <JsonView value={messages} />
  return (
    <div className="space-y-2 text-sm">
      {system != null && (
        <details className="rounded-md bg-[var(--surface-2)] p-2">
          <summary className="cursor-pointer text-xs font-medium text-[var(--ink-2)]">system prompt</summary>
          <div className="mt-2 whitespace-pre-wrap text-xs text-[var(--ink-2)]">
            {typeof system === 'string' ? system : JSON.stringify(system, null, 2)}
          </div>
        </details>
      )}
      {messages.map((m: { role?: string; content?: unknown; parts?: unknown }, i: number) => (
        <div key={i} className="flex gap-2">
          <div className="w-16 shrink-0 pt-0.5 text-right text-[11px] uppercase tracking-wide text-[var(--muted)]">
            {m.role}
          </div>
          <div className="min-w-0 flex-1 space-y-1.5">
            {blocksOf(m.content ?? m.parts).map((b, j) => (
              <BlockView key={j} b={b} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function OutputBlocks({ output }: { output: unknown }) {
  const o = output as { content?: unknown; message?: { content?: unknown }; stop_reason?: string } | null
  if (o && Array.isArray(o.content))
    return (
      <div className="space-y-1.5 text-sm">
        {(o.content as Block[]).map((b, i) => <BlockView key={i} b={b} />)}
        {o.stop_reason && <div className="text-xs text-[var(--muted)]">stop_reason: {o.stop_reason}</div>}
      </div>
    )
  if (o && o.message) return <Messages messages={[o.message]} />
  if (Array.isArray(output)) return <Messages messages={output} />
  return <JsonView value={output} />
}
