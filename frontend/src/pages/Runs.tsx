import { GitCompare } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Sparkline } from '../components/Sparkline'
import { Empty, ErrorBox, PageHeader, Select } from '../components/ui'
import { api, type Run } from '../lib/api'
import { ago, ms, pct, runName, shortSha, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

function PassBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[var(--surface-3)]">
        <div className="h-full rounded-full bg-[var(--series-1)]" style={{ width: `${value * 100}%` }} />
      </div>
      <span className="tnum">{pct(value)}</span>
    </div>
  )
}

export default function RunsPage() {
  const { data, error } = useFetch(() => api.runs(), [])
  const [suite, setSuite] = useState('')
  const [model, setModel] = useState('')
  const [sha, setSha] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const navigate = useNavigate()

  const runs = useMemo(
    () =>
      (data ?? []).filter(
        (r) =>
          (!suite || r.suite === suite) &&
          (!model || r.model === model) &&
          (!sha || (r.git_sha ?? '').startsWith(sha.trim())),
      ),
    [data, suite, model, sha],
  )
  const bySuite = useMemo(() => {
    const m = new Map<string, Run[]>()
    for (const r of [...runs].reverse()) m.set(r.suite, [...(m.get(r.suite) ?? []), r])
    return m
  }, [runs])

  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const suites = [...new Set(data.map((r) => r.suite))]
  const models = [...new Set(data.map((r) => r.model).filter(Boolean))] as string[]
  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]))

  return (
    <>
      <PageHeader
        title="Runs"
        subtitle="Every eval run in this database. Pick two to compare."
        actions={
          <button
            type="button"
            disabled={picked.length !== 2}
            onClick={() => {
              const [a, b] = [...picked].sort(
                (x, y) =>
                  new Date(data.find((r) => r.run_id === x)!.created_at).getTime() -
                  new Date(data.find((r) => r.run_id === y)!.created_at).getTime(),
              )
              navigate(`/compare?a=${a}&b=${b}`)
            }}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-40"
          >
            <GitCompare size={15} /> Compare {picked.length}/2
          </button>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-4">
        <Select label="Suite" value={suite} onChange={setSuite} options={[{ value: '', label: 'All suites' }, ...suites.map((s) => ({ value: s, label: s }))]} />
        <Select label="Model" value={model} onChange={setModel} options={[{ value: '', label: 'All models' }, ...models.map((s) => ({ value: s, label: s }))]} />
        <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
          Git SHA
          <input
            value={sha}
            onChange={(e) => setSha(e.target.value)}
            placeholder="e.g. 3f2a9c1"
            className="w-32 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 font-mono text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          />
        </label>
      </div>

      {runs.length === 0 ? (
        <Empty>
          No runs match. Create one with <code className="font-mono">tracejudge eval suite.yaml</code> or
          load the samples with <code className="font-mono">make demo</code>.
        </Empty>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[...bySuite.entries()].map(([name, rs]) => {
              const last = rs[rs.length - 1]
              const prev = rs[rs.length - 2]
              return (
                <div key={name} className="card flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{name}</div>
                    <div className="mt-1 text-2xl font-semibold">{pct(last.summary.pass_rate)}</div>
                    <div className="text-xs text-[var(--muted)]">
                      latest pass rate · {rs.length} run{rs.length > 1 ? 's' : ''}
                      {prev && ` · was ${pct(prev.summary.pass_rate)}`}
                    </div>
                  </div>
                  <Sparkline width={140} height={48} points={rs.map((r) => ({ value: r.summary.pass_rate, label: runName(r) }))} />
                </div>
              )
            })}
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-[var(--muted)]">
                <tr className="border-b border-[var(--border)]">
                  <th className="w-10 px-4 py-2" />
                  <th className="px-2 py-2 font-normal">Run</th>
                  <th className="px-2 py-2 font-normal">Suite</th>
                  <th className="px-2 py-2 font-normal">Agent · model</th>
                  <th className="px-2 py-2 font-normal">SHA</th>
                  <th className="px-2 py-2 font-normal">Pass rate</th>
                  <th className="px-2 py-2 font-normal">pass^k</th>
                  <th className="px-2 py-2 text-right font-normal">Flaky</th>
                  <th className="px-2 py-2 text-right font-normal">Cost/trial</th>
                  <th className="px-2 py-2 text-right font-normal">p95</th>
                  <th className="px-4 py-2 text-right font-normal">When</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.run_id}
                    className="cursor-pointer border-b border-[var(--border)]/50 last:border-0 hover:bg-[var(--surface-2)]"
                    onClick={() => navigate(`/runs/${r.run_id}`)}
                  >
                    <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`select ${runName(r)} for comparison`}
                        checked={picked.includes(r.run_id)}
                        onChange={() => toggle(r.run_id)}
                        className="accent-[var(--accent)]"
                      />
                    </td>
                    <td className="px-2 py-2.5">
                      <Link to={`/runs/${r.run_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
                        {runName(r)}
                      </Link>
                      {r.label && <div className="font-mono text-[11px] text-[var(--muted)]">{r.run_id}</div>}
                    </td>
                    <td className="px-2 py-2.5 text-[var(--ink-2)]">{r.suite}</td>
                    <td className="max-w-[260px] px-2 py-2.5">
                      <div className="truncate font-mono text-xs">{r.agent}</div>
                      <div className="truncate text-xs text-[var(--muted)]">{r.model ?? '–'}</div>
                    </td>
                    <td className="px-2 py-2.5 font-mono text-xs text-[var(--ink-2)]">{shortSha(r.git_sha)}</td>
                    <td className="px-2 py-2.5"><PassBar value={r.summary.pass_rate} /></td>
                    <td className="px-2 py-2.5 tnum">{pct(r.summary.pass_hat_k)}</td>
                    <td className="px-2 py-2.5 text-right tnum">{r.summary.flaky_cases?.length ?? 0}</td>
                    <td className="px-2 py-2.5 text-right tnum">{usd(r.summary.cost_per_trial_usd)}</td>
                    <td className="px-2 py-2.5 text-right tnum">{ms(r.summary.latency_p95_ms)}</td>
                    <td className="px-4 py-2.5 text-right text-xs text-[var(--muted)]" title={r.created_at}>{ago(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
