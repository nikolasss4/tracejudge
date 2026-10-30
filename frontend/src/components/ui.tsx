import { Check, CircleSlash, X } from 'lucide-react'
import type { ReactNode } from 'react'

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 text-sm text-[var(--ink-2)]">{subtitle}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatTile({
  label,
  value,
  delta,
  hint,
  children,
}: {
  label: string
  value: ReactNode
  delta?: ReactNode
  hint?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="card min-w-0 p-4">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <div className="text-2xl font-semibold">{value}</div>
        {delta}
      </div>
      {hint && <div className="mt-1 text-xs text-[var(--ink-2)]">{hint}</div>}
      {children}
    </div>
  )
}

/** Signed change, coloured by direction × whether up is good, with an arrow (never colour alone). */
export function Delta({ value, text, upIsGood = true }: { value: number; text: string; upIsGood?: boolean }) {
  if (Math.abs(value) < 1e-12) return <span className="text-xs text-[var(--muted)]">±0</span>
  const good = value > 0 === upIsGood
  return (
    <span
      className="text-xs font-medium"
      style={{ color: good ? 'var(--good-ink)' : 'var(--critical-ink)' }}
    >
      {value > 0 ? '▲' : '▼'} {text}
    </span>
  )
}

export function PassBadge({ passed, skipped }: { passed: boolean | null; skipped?: boolean }) {
  if (passed === null || skipped)
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-3)] px-2 py-0.5 text-xs text-[var(--ink-2)]">
        <CircleSlash size={12} /> skipped
      </span>
    )
  return passed ? (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-[var(--good-ink)] ring-1 ring-[var(--good)]/40">
      <Check size={12} strokeWidth={3} /> pass
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-[var(--critical-ink)] ring-1 ring-[var(--critical)]/50">
      <X size={12} strokeWidth={3} /> fail
    </span>
  )
}

/** One mark per trial: filled check for pass, hollow cross for fail. */
export function TrialDots({
  trials,
  onSelect,
  selected,
}: {
  trials: { id: string; trial: number; passed: boolean }[]
  onSelect?: (id: string) => void
  selected?: string | null
}) {
  return (
    <div className="flex items-center gap-1">
      {trials.map((t) => (
        <button
          key={t.id}
          type="button"
          title={`trial ${t.trial}: ${t.passed ? 'pass' : 'fail'}`}
          aria-label={`trial ${t.trial}: ${t.passed ? 'pass' : 'fail'}`}
          onClick={(e) => {
            e.stopPropagation()
            onSelect?.(t.id)
          }}
          className={`grid h-5 w-5 place-items-center rounded-full transition hover:scale-110 ${
            selected === t.id ? 'ring-2 ring-[var(--accent)] ring-offset-2 ring-offset-[var(--surface)]' : ''
          }`}
          style={
            t.passed
              ? { background: 'var(--good)', color: 'var(--surface)' }
              : { boxShadow: 'inset 0 0 0 1.5px var(--critical)', color: 'var(--critical-ink)' }
          }
        >
          {t.passed ? <Check size={11} strokeWidth={3.5} /> : <X size={11} strokeWidth={3.5} />}
        </button>
      ))}
    </div>
  )
}

export function Chip({ children, active, onClick }: { children: ReactNode; active?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-xs transition ${
        active
          ? 'bg-[var(--accent)] text-white'
          : 'bg-[var(--surface-2)] text-[var(--ink-2)] hover:bg-[var(--surface-3)]'
      }`}
    >
      {children}
    </button>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card p-10 text-center text-sm text-[var(--ink-2)]">{children}</div>
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="card border-[var(--critical)]/40 p-4 text-sm text-[var(--critical-ink)]">{error}</div>
  )
}

export function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  label: string
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export const KIND_COLOR: Record<string, string> = {
  llm: 'var(--series-1)',
  tool: 'var(--series-2)',
  retrieval: 'var(--series-3)',
  custom: 'var(--series-5)',
  agent: 'var(--neutral-mark)',
}
