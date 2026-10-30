import { GitCompare, Search, Tags } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Chip, ErrorBox, PageHeader, StatTile, TrialDots } from '../components/ui'
import { api } from '../lib/api'
import { ms, pct, runName, shortSha, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

type Filter = 'all' | 'failing' | 'flaky' | 'passing'

export default function RunDetailPage() {
  const { id = '' } = useParams()
  const { data, error } = useFetch(() => api.run(id), [id])
  const runs = useFetch(() => api.runs(), [])
  const [filter, setFilter] = useState<Filter>('all')
  const [tag, setTag] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const navigate = useNavigate()

  const cases = useMemo(() => {
    if (!data) return []
    return data.cases.filter((c) => {
      if (filter === 'failing' && c.passed === c.trials) return false
      if (filter === 'passing' && c.passed < c.trials) return false
      if (filter === 'flaky' && (c.passed === 0 || c.passed === c.trials)) return false
      if (tag && !c.tags.includes(tag)) return false
      return !q || c.case_id.includes(q)
    })
  }, [data, filter, tag, q])

  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const { run } = data
  const s = run.summary
  const tags = [...new Set(data.cases.flatMap((c) => c.tags))].sort()
  const failing = data.cases.filter((c) => c.passed < c.trials).length
  const maxFail = Math.max(1, ...(s.top_failures ?? []).map(([, n]) => n))
  const others = (runs.data ?? []).filter((r) => r.suite === run.suite && r.run_id !== run.run_id)

  return (
    <>
      <PageHeader
        title={runName(run)}
        subtitle={
          <span className="flex flex-wrap gap-x-3 gap-y-1">
            <span>{run.suite}</span>
            <span className="font-mono text-xs">{run.agent}</span>
            {run.model && <span>{run.model}</span>}
            {run.git_sha && <span className="font-mono text-xs">@{shortSha(run.git_sha)}{run.git_branch ? ` (${run.git_branch})` : ''}</span>}
            <span className="text-[var(--muted)]">{new Date(run.created_at).toLocaleString()}</span>
          </span>
        }
        actions={
          <>
            {others.length > 0 && (
              <select
                aria-label="compare with another run"
                className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-sm"
                value=""
                onChange={(e) => navigate(`/compare?a=${e.target.value}&b=${run.run_id}`)}
              >
                <option value="">Compare against…</option>
                {others.map((r) => (
                  <option key={r.run_id} value={r.run_id}>{runName(r)} ({pct(r.summary.pass_rate)})</option>
                ))}
              </select>
            )}
            <Link to={`/label?run=${run.run_id}`} className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm hover:bg-[var(--surface-2)]">
              <Tags size={15} /> Label
            </Link>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Pass rate" value={pct(s.pass_rate)} hint={`95% CI ${pct(s.pass_rate_ci95[0])}–${pct(s.pass_rate_ci95[1])}`} />
        <StatTile label={`pass^${s.k} (every trial passes)`} value={pct(s.pass_hat_k)} hint={`pass@${s.k} ${pct(s.pass_at_k)}`} />
        <StatTile label="Flaky cases" value={s.flaky_cases.length} hint={`${failing} of ${s.cases} cases fail ≥1 trial`} />
        <StatTile label="Cost / trial" value={usd(s.cost_per_trial_usd)} hint={`${usd(s.cost_usd)} total`} />
        <StatTile label="Latency p50 / p95" value={ms(s.latency_p50_ms)} hint={`p95 ${ms(s.latency_p95_ms)}`} />
        <StatTile label="Trials" value={s.trials} hint={`${s.cases} cases × ${s.repeats} · ${s.mean_steps.toFixed(1)} LLM steps avg`} />
      </div>

      {(s.top_failures?.length ?? 0) > 0 && (
        <section className="card mb-6 p-4">
          <h2 className="mb-3 text-sm font-medium">Failing checks <span className="font-normal text-[var(--muted)]">· failed trials per scorer</span></h2>
          <div className="space-y-1.5">
            {s.top_failures.map(([name, n]) => (
              <div key={name} className="grid grid-cols-[minmax(0,50%)_1fr] items-center gap-3 text-sm sm:grid-cols-[minmax(0,260px)_1fr]">
                <span className="truncate font-mono text-xs text-[var(--ink-2)]" title={name}>{name}</span>
                <div className="flex items-center gap-2">
                  <div className="h-3 rounded-r-[4px] bg-[var(--critical)]" style={{ width: `${(n / maxFail) * 100}%`, maxWidth: 'calc(100% - 3rem)' }} />
                  <span className="text-xs tnum text-[var(--ink-2)]">{n}</span>
                </div>
              </div>
            ))}
          </div>
          {!!s.skipped_scores && (
            <p className="mt-3 text-xs text-[var(--muted)]">
              {s.skipped_scores} judge verdicts were skipped (no recorded fixture and no API key) and don't count towards pass or fail.
            </p>
          )}
        </section>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {(['all', 'failing', 'flaky', 'passing'] as Filter[]).map((f) => (
          <Chip key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</Chip>
        ))}
        <span className="mx-1 h-4 w-px bg-[var(--border)]" />
        {tags.map((t) => (
          <Chip key={t} active={tag === t} onClick={() => setTag(tag === t ? null : t)}>#{t}</Chip>
        ))}
        <label className="ml-auto flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1">
          <Search size={14} className="text-[var(--muted)]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter cases" className="w-40 bg-transparent text-sm outline-none" />
        </label>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-[var(--muted)]">
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-2 font-normal">Case</th>
              <th className="px-2 py-2 font-normal">Trials</th>
              <th className="px-2 py-2 font-normal">Failing checks</th>
              <th className="px-2 py-2 text-right font-normal">Steps</th>
              <th className="px-2 py-2 text-right font-normal">Cost</th>
              <th className="px-4 py-2 text-right font-normal">Latency</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.case_id}
                className="cursor-pointer border-b border-[var(--border)]/50 last:border-0 hover:bg-[var(--surface-2)]"
                onClick={() => navigate(`/results/${(c.results.find((r) => !r.passed) ?? c.results[0]).id}`)}
              >
                <td className="px-4 py-2.5">
                  <div className="font-medium">{c.case_id}</div>
                  <div className="text-[11px] text-[var(--muted)]">{c.tags.map((t) => `#${t}`).join(' ')}</div>
                </td>
                <td className="px-2 py-2.5"><TrialDots trials={c.results} onSelect={(rid) => navigate(`/results/${rid}`)} /></td>
                <td className="max-w-md px-2 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    {c.failing.map((f) => (
                      <span key={f} className="rounded bg-[var(--surface-3)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--ink-2)]">{f}</span>
                    ))}
                  </div>
                </td>
                <td className="px-2 py-2.5 text-right tnum">{c.steps.toFixed(1)}</td>
                <td className="px-2 py-2.5 text-right tnum">{usd(c.cost_usd)}</td>
                <td className="px-4 py-2.5 text-right tnum">{ms(c.latency_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {cases.length === 0 && <div className="p-8 text-center text-sm text-[var(--muted)]">No cases match.</div>}
      </div>
      <p className="mt-3 text-xs text-[var(--muted)]">
        <GitCompare size={12} className="mr-1 inline" />
        Click a case to open its trace; failing trials open first.
      </p>
    </>
  )
}
