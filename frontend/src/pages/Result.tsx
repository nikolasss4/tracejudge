import { ChevronLeft } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { TraceView } from '../components/TraceView'
import { ErrorBox, PassBadge, TrialDots } from '../components/ui'
import { api, type Score } from '../lib/api'
import { compact, ms, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

function ScoreRow({ s }: { s: Score }) {
  return (
    <li className="flex items-start gap-3 py-2">
      <PassBadge passed={s.passed} />
      <div className="min-w-0">
        <div className="font-mono text-xs">
          <span className="text-[var(--muted)]">{s.scorer}:</span>
          {s.name}
        </div>
        <div className="text-sm text-[var(--ink-2)]">{s.reason}</div>
      </div>
    </li>
  )
}

export default function ResultPage() {
  const { id = '' } = useParams()
  const { data, error } = useFetch(() => api.result(id), [id])
  const runRes = useFetch(() => (data ? api.run(data.result.run_id) : Promise.resolve(null)), [data?.result.run_id])
  const navigate = useNavigate()
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  const r = data.result
  const siblings = runRes.data?.cases.find((c) => c.case_id === r.case_id)?.results ?? []
  const failed = r.scores.filter((s) => s.passed === false)
  const rest = r.scores.filter((s) => s.passed !== false)
  return (
    <>
      <Link to={`/runs/${r.run_id}`} className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-2)] hover:text-[var(--ink)]">
        <ChevronLeft size={15} /> {runRes.data?.run.label ?? r.run_id}
      </Link>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{r.case_id}</h1>
        <span className="text-sm text-[var(--muted)]">trial {r.trial}</span>
        <PassBadge passed={r.passed} />
        {siblings.length > 1 && <TrialDots trials={siblings} selected={r.id} onSelect={(rid) => navigate(`/results/${rid}`)} />}
        <span className="ml-auto text-sm text-[var(--ink-2)] tnum">
          {ms(r.latency_ms)} · {r.steps} LLM steps · {compact(r.input_tokens + r.output_tokens)} tokens · {usd(r.cost_usd)}
        </span>
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Input</h2>
          <div className="whitespace-pre-wrap text-sm">{typeof r.input?.message === 'string' ? r.input.message : JSON.stringify(r.input, null, 2)}</div>
          {r.input?.customer_id && <div className="mt-1 text-xs text-[var(--muted)]">customer {r.input.customer_id}</div>}
          <h2 className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Final answer</h2>
          <div className="whitespace-pre-wrap text-sm">{r.error ? <span className="text-[var(--critical-ink)]">{r.error}</span> : typeof r.output === 'string' ? r.output : JSON.stringify(r.output, null, 2)}</div>
        </section>
        <section className="card p-4">
          <h2 className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
            Checks · {r.scores.filter((s) => s.passed).length} pass, {failed.length} fail
          </h2>
          <ul className="max-h-72 divide-y divide-[var(--border)] overflow-auto">
            {[...failed, ...rest].map((s, i) => <ScoreRow key={i} s={s} />)}
          </ul>
        </section>
      </div>

      {data.trace ? <TraceView trace={data.trace} /> : <div className="card p-4 text-sm">No trace recorded.</div>}
    </>
  )
}
