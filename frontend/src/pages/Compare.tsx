import { ArrowRight, ExternalLink } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { TraceView } from '../components/TraceView'
import { Chip, Delta, Empty, ErrorBox, PageHeader, StatTile } from '../components/ui'
import { api, type CaseDiff, type CaseStatus } from '../lib/api'
import { ms, pct, pts, rel, runName, shortSha, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

const STATUS: Record<CaseStatus, { label: string; color: string; icon: string }> = {
  regressed: { label: 'regressed', color: 'var(--critical-ink)', icon: '▼' },
  degraded: { label: 'less reliable', color: 'var(--serious)', icon: '▽' },
  fixed: { label: 'fixed', color: 'var(--good-ink)', icon: '▲' },
  improved: { label: 'more reliable', color: 'var(--good-ink)', icon: '△' },
  unchanged: { label: 'unchanged', color: 'var(--muted)', icon: '·' },
  added: { label: 'added', color: 'var(--ink-2)', icon: '+' },
  removed: { label: 'removed', color: 'var(--ink-2)', icon: '−' },
}
const ORDER: CaseStatus[] = ['regressed', 'degraded', 'fixed', 'improved', 'added', 'removed', 'unchanged']

function StatusTag({ s }: { s: CaseStatus }) {
  const st = STATUS[s]
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium" style={{ color: st.color }}>
      <span aria-hidden>{st.icon}</span>
      {st.label}
    </span>
  )
}

function RunPicker({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const { data } = useFetch(() => api.runs(), [])
  return (
    <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="max-w-[260px] rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm text-[var(--ink)]">
        <option value="">Pick a run…</option>
        {(data ?? []).map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {runName(r)} · {r.suite} · {pct(r.summary.pass_rate)}
          </option>
        ))}
      </select>
    </label>
  )
}

function Trajectories({ c, forward }: { c: CaseDiff; forward: boolean }) {
  const n = Math.max(c.trajectory_a.length, c.trajectory_b.length)
  const d = c.diverged_at
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-[var(--muted)]">
          <tr>
            <th className="w-10 py-1 font-normal">step</th>
            <th className="py-1 font-normal">baseline · {forward ? 'a passing' : 'a failing'} trial</th>
            <th className="py-1 font-normal">candidate · {forward ? 'a failing' : 'a passing'} trial</th>
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: n }, (_, i) => {
            const a = c.trajectory_a[i]
            const b = c.trajectory_b[i]
            const at = d === i
            const after = d != null && i > d
            return (
              <tr key={i} className={after ? 'opacity-60' : ''}>
                <td className="py-1 align-top text-xs text-[var(--muted)] tnum">{i + 1}</td>
                <td className="py-1 pr-3">
                  {a ? (
                    <span className={`inline-block rounded-md px-2 py-1 font-mono text-xs ${at ? 'ring-1 ring-[var(--accent)]' : 'bg-[var(--surface-2)]'}`}>{a}</span>
                  ) : (
                    <span className="text-xs text-[var(--muted)]">(end)</span>
                  )}
                </td>
                <td className="py-1">
                  {b ? (
                    <span
                      className={`inline-block rounded-md px-2 py-1 font-mono text-xs ${at ? 'bg-[var(--critical)]/20 text-[var(--critical-ink)] ring-1 ring-[var(--critical)]' : 'bg-[var(--surface-2)]'}`}
                    >
                      {b}
                    </span>
                  ) : (
                    <span className={`text-xs ${at ? 'text-[var(--critical-ink)]' : 'text-[var(--muted)]'}`}>(end)</span>
                  )}
                  {at && <span className="ml-2 text-xs font-medium text-[var(--critical-ink)]">← trajectories split here</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CasePanel({ c }: { c: CaseDiff }) {
  const [side, setSide] = useState<'a' | 'b'>('b')
  const tid = side === 'a' ? c.trial_a : c.trial_b
  const res = useFetch(() => (tid ? api.result(tid) : Promise.resolve(null)), [tid])
  const forward = c.status === 'regressed' || c.status === 'degraded'
  return (
    <div className="space-y-4">
      <section className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 className="font-medium">{c.case_id}</h2>
          <StatusTag s={c.status} />
          <span className="text-sm text-[var(--ink-2)] tnum">
            {c.a_passed}/{c.a_trials} <ArrowRight size={12} className="inline" /> {c.b_passed}/{c.b_trials} trials pass
          </span>
          {c.p_value != null && <span className="text-xs text-[var(--muted)]">Fisher p = {c.p_value.toFixed(2)}</span>}
        </div>
        {c.trajectory_a.length + c.trajectory_b.length > 0 ? (
          <Trajectories c={c} forward={forward} />
        ) : (
          <p className="text-sm text-[var(--muted)]">Outcome unchanged; no trajectory comparison.</p>
        )}
        {c.reasons.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Why the candidate fails</h3>
            <ul className="space-y-1 text-sm">
              {c.reasons.map((r) => (
                <li key={r} className="font-mono text-xs text-[var(--ink-2)]">{r}</li>
              ))}
            </ul>
          </div>
        )}
      </section>
      {(c.trial_a || c.trial_b) && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            <Chip active={side === 'a'} onClick={() => setSide('a')}>baseline trace</Chip>
            <Chip active={side === 'b'} onClick={() => setSide('b')}>candidate trace</Chip>
            {tid && (
              <Link to={`/results/${tid}`} className="ml-auto inline-flex items-center gap-1 text-xs text-[var(--ink-2)] hover:text-[var(--ink)]">
                open <ExternalLink size={12} />
              </Link>
            )}
          </div>
          {res.data?.trace && <TraceView key={tid} trace={res.data.trace} divergeAt={c.diverged_at} />}
        </section>
      )}
    </div>
  )
}

export default function Compare() {
  const [params, setParams] = useSearchParams()
  const a = params.get('a') ?? ''
  const b = params.get('b') ?? ''
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    next.set(k, v)
    next.delete('case')
    setParams(next)
  }
  const { data, error } = useFetch(() => (a && b ? api.diff(a, b) : Promise.resolve(null)), [a, b])
  const [status, setStatus] = useState<'changed' | CaseStatus>('changed')
  const selectedId = params.get('case')

  const cases = useMemo(() => {
    const all = [...(data?.cases ?? [])].sort((x, y) => ORDER.indexOf(x.status) - ORDER.indexOf(y.status) || x.case_id.localeCompare(y.case_id))
    return all.filter((c) => (status === 'changed' ? c.status !== 'unchanged' : c.status === status))
  }, [data, status])
  const selected = data?.cases.find((c) => c.case_id === selectedId) ?? cases[0]

  useEffect(() => setStatus('changed'), [a, b])

  const pickers = (
    <div className="flex flex-wrap items-center gap-3">
      <RunPicker label="Baseline" value={a} onChange={(v) => set('a', v)} />
      <ArrowRight size={14} className="text-[var(--muted)]" />
      <RunPicker label="Candidate" value={b} onChange={(v) => set('b', v)} />
    </div>
  )
  if (!a || !b)
    return (
      <>
        <PageHeader title="Compare runs" subtitle="Which cases flipped, where trajectories diverged, and whether it could be noise." />
        <div className="mb-4">{pickers}</div>
        <Empty>Pick a baseline and a candidate run.</Empty>
      </>
    )
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const counts = ORDER.map((s) => [s, data.cases.filter((c) => c.status === s).length] as const)
  const k = data.b.summary.k ?? 3

  return (
    <>
      <PageHeader
        title={<>{runName(data.a)} <ArrowRight size={18} className="inline text-[var(--muted)]" /> {runName(data.b)}</>}
        subtitle={<>{data.b.suite}{data.a.git_sha && ` · ${shortSha(data.a.git_sha)} → ${shortSha(data.b.git_sha)}`}</>}
      />
      <div className="mb-5">{pickers}</div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatTile label="Pass rate" value={pct(data.pass_rate_b)} delta={<Delta value={data.pass_rate_delta} text={pts(data.pass_rate_delta)} />} hint={`was ${pct(data.pass_rate_a)}`} />
        <StatTile
          label={`pass^${k}`}
          value={pct(data.b.summary.pass_hat_k)}
          delta={<Delta value={data.b.summary.pass_hat_k - data.a.summary.pass_hat_k} text={pts(data.b.summary.pass_hat_k - data.a.summary.pass_hat_k)} />}
          hint={`was ${pct(data.a.summary.pass_hat_k)}`}
        />
        <StatTile label="Regressed cases" value={counts.find(([s]) => s === 'regressed')![1]} hint={`${counts.find(([s]) => s === 'fixed')![1]} fixed · ${counts.find(([s]) => s === 'degraded')![1]} less reliable`} />
        <StatTile
          label="Cost / trial"
          value={usd(data.cost_per_trial_b)}
          delta={<Delta value={data.cost_per_trial_b - data.cost_per_trial_a} text={rel(data.cost_per_trial_a, data.cost_per_trial_b)} upIsGood={false} />}
          hint={`was ${usd(data.cost_per_trial_a)}`}
        />
        <StatTile
          label="Latency p95"
          value={ms(data.latency_p95_b)}
          delta={<Delta value={data.latency_p95_b - data.latency_p95_a} text={rel(data.latency_p95_a, data.latency_p95_b)} upIsGood={false} />}
          hint={`p50 ${ms(data.latency_p50_a)} → ${ms(data.latency_p50_b)}`}
        />
      </div>
      {data.notes.length > 0 && (
        <div className="card mb-6 p-4 text-sm text-[var(--ink-2)]">
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Is this noise?</div>
          <ul className="list-disc space-y-1 pl-5">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Chip active={status === 'changed'} onClick={() => setStatus('changed')}>changed {data.cases.filter((c) => c.status !== 'unchanged').length}</Chip>
            {counts.filter(([, n]) => n > 0).map(([s, n]) => (
              <Chip key={s} active={status === s} onClick={() => setStatus(s)}>{STATUS[s].label} {n}</Chip>
            ))}
          </div>
          <div className="card max-h-[70vh] overflow-auto">
            {cases.length === 0 && <div className="p-6 text-center text-sm text-[var(--muted)]">No cases.</div>}
            {cases.map((c) => (
              <button
                key={c.case_id}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params)
                  next.set('case', c.case_id)
                  setParams(next, { replace: true })
                }}
                className={`flex w-full items-center justify-between gap-3 border-b border-[var(--border)]/50 px-3 py-2 text-left last:border-0 ${
                  selected?.case_id === c.case_id ? 'bg-[var(--surface-3)]' : 'hover:bg-[var(--surface-2)]'
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate text-sm">{c.case_id}</div>
                  <StatusTag s={c.status} />
                </div>
                <span className="shrink-0 text-xs text-[var(--ink-2)] tnum">
                  {c.a_passed}/{c.a_trials} → {c.b_passed}/{c.b_trials}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-0">{selected ? <CasePanel key={selected.case_id} c={selected} /> : <Empty>No case changed outcome.</Empty>}</div>
      </div>
    </>
  )
}
