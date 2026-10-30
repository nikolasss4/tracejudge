import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ChartCard, ColumnChart, Histogram, Legend, LineChart } from '../components/Charts'
import { Empty, ErrorBox, PageHeader, Select, StatTile } from '../components/ui'
import { api } from '../lib/api'
import { compact, ms, runName, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

export default function Dashboard() {
  const { data, error } = useFetch(() => api.runs(), [])
  const [suite, setSuite] = useState('')
  const [runId, setRunId] = useState('')
  const suites = useMemo(() => [...new Set((data ?? []).map((r) => r.suite))], [data])
  const activeSuite = suite || suites[0] || ''
  const runs = useMemo(() => (data ?? []).filter((r) => r.suite === activeSuite).reverse(), [data, activeSuite])
  const selected = runId && runs.some((r) => r.run_id === runId) ? runId : runs[runs.length - 1]?.run_id ?? ''
  const detail = useFetch(() => (selected ? api.run(selected) : Promise.resolve(null)), [selected])

  if (error) return <ErrorBox error={error} />
  if (!data) return null
  if (runs.length === 0) return <Empty>No runs yet.</Empty>

  const latest = runs[runs.length - 1]
  const labels = runs.map(runName)
  const trials = detail.data?.trials ?? []
  const costly = [...(detail.data?.cases ?? [])].sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 8)
  const simulated = runs.some((r) => (r.model ?? '').startsWith('simulated'))

  return (
    <>
      <PageHeader title="Cost & latency" subtitle="Per-run spend and speed for one suite, plus the trial-level distribution of a selected run." />
      <div className="mb-5 flex flex-wrap items-center gap-4">
        <Select label="Suite" value={activeSuite} onChange={setSuite} options={suites.map((s) => ({ value: s, label: s }))} />
        <Select label="Run" value={selected} onChange={setRunId} options={runs.map((r) => ({ value: r.run_id, label: runName(r) }))} />
      </div>
      {simulated && (
        <p className="mb-4 text-xs text-[var(--muted)]">
          Runs on the simulated model use estimated tokens (≈4 characters per token) priced at claude-sonnet-5-5 rates, and simulated latency.
        </p>
      )}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Cost / trial (latest)" value={usd(latest.summary.cost_per_trial_usd)} hint={runName(latest)} />
        <StatTile label="Total spend (all runs)" value={usd(runs.reduce((s, r) => s + r.summary.cost_usd, 0))} hint={`${runs.length} runs`} />
        <StatTile label="Tokens (latest)" value={compact(latest.summary.tokens)} hint={`${compact(latest.summary.tokens / Math.max(latest.summary.trials, 1))} per trial`} />
        <StatTile label="Latency p95 (latest)" value={ms(latest.summary.latency_p95_ms)} hint={`p50 ${ms(latest.summary.latency_p50_ms)}`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Cost per trial" subtitle="mean USD per trial, by run">
          <ColumnChart data={runs.map((r) => ({ label: runName(r), value: r.summary.cost_per_trial_usd, sub: r.model ?? '' }))} fmt={usd} valueLabel="per trial" />
        </ChartCard>
        <ChartCard
          title="Trial latency"
          subtitle="p50 and p95 across trials, by run"
          legend={<Legend items={[{ label: 'p50', color: 'var(--series-1)' }, { label: 'p95', color: 'var(--series-2)' }]} />}
        >
          <LineChart
            labels={labels}
            fmt={ms}
            series={[
              { name: 'p50', color: 'var(--series-1)', values: runs.map((r) => r.summary.latency_p50_ms) },
              { name: 'p95', color: 'var(--series-2)', values: runs.map((r) => r.summary.latency_p95_ms) },
            ]}
          />
        </ChartCard>
        <ChartCard title="Latency distribution" subtitle={`${trials.length} trials in ${runs.find((r) => r.run_id === selected) ? runName(runs.find((r) => r.run_id === selected)!) : ''}`}>
          <Histogram values={trials.map((t) => t.latency_ms)} fmt={ms} />
        </ChartCard>
        <ChartCard title="Most expensive cases" subtitle="mean cost per trial in the selected run">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--muted)]">
              <tr>
                <th className="py-1 font-normal">case</th>
                <th className="py-1 text-right font-normal">steps</th>
                <th className="py-1 text-right font-normal">latency</th>
                <th className="py-1 text-right font-normal">cost</th>
              </tr>
            </thead>
            <tbody>
              {costly.map((c) => (
                <tr key={c.case_id} className="border-t border-[var(--border)]/50">
                  <td className="py-1.5"><Link className="hover:underline" to={`/results/${c.results[0].id}`}>{c.case_id}</Link></td>
                  <td className="py-1.5 text-right tnum">{c.steps.toFixed(1)}</td>
                  <td className="py-1.5 text-right tnum">{ms(c.latency_ms)}</td>
                  <td className="py-1.5 text-right tnum">{usd(c.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
      </div>
    </>
  )
}
