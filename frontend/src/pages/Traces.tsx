import { ChevronLeft } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { TraceView } from '../components/TraceView'
import { Empty, ErrorBox, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { compact, ms, usd } from '../lib/format'
import { useFetch } from '../lib/useFetch'

export function TracesPage() {
  const { data, error } = useFetch(() => api.traces(), [])
  const navigate = useNavigate()
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  return (
    <>
      <PageHeader
        title="Traces"
        subtitle={<>Traces sent outside eval runs: from the SDK, or over OTLP to <code className="font-mono">POST /v1/traces</code>.</>}
      />
      {data.length === 0 ? (
        <Empty>
          No standalone traces yet. Point an OpenTelemetry exporter at this server:
          <pre className="mt-3 inline-block rounded-md bg-[var(--surface-2)] px-3 py-2 text-left font-mono text-xs">
            OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:7600/v1/traces
          </pre>
        </Empty>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--muted)]">
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-2 font-normal">Trace</th>
                <th className="px-2 py-2 font-normal">Source</th>
                <th className="px-2 py-2 text-right font-normal">Spans</th>
                <th className="px-2 py-2 text-right font-normal">Errors</th>
                <th className="px-2 py-2 text-right font-normal">Tokens</th>
                <th className="px-2 py-2 text-right font-normal">Cost</th>
                <th className="px-2 py-2 text-right font-normal">Duration</th>
                <th className="px-4 py-2 text-right font-normal">Started</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.trace_id} onClick={() => navigate(`/traces/${t.trace_id}`)} className="cursor-pointer border-b border-[var(--border)]/50 last:border-0 hover:bg-[var(--surface-2)]">
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{t.name}</div>
                    <div className="font-mono text-[11px] text-[var(--muted)]">{t.trace_id}</div>
                  </td>
                  <td className="px-2 py-2.5 text-[var(--ink-2)]">{t.source}</td>
                  <td className="px-2 py-2.5 text-right tnum">{t.spans}</td>
                  <td className="px-2 py-2.5 text-right tnum" style={{ color: t.errors ? 'var(--critical-ink)' : undefined }}>{t.errors}</td>
                  <td className="px-2 py-2.5 text-right tnum">{compact(t.tokens)}</td>
                  <td className="px-2 py-2.5 text-right tnum">{usd(t.cost_usd)}</td>
                  <td className="px-2 py-2.5 text-right tnum">{t.end_ns ? ms((t.end_ns - t.start_ns) / 1e6) : '–'}</td>
                  <td className="px-4 py-2.5 text-right text-xs text-[var(--muted)]">{new Date(t.start_ns / 1e6).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export function TracePage() {
  const { id = '' } = useParams()
  const { data, error } = useFetch(() => api.trace(id), [id])
  if (error) return <ErrorBox error={error} />
  if (!data) return null
  return (
    <>
      <Link to="/traces" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-2)] hover:text-[var(--ink)]">
        <ChevronLeft size={15} /> Traces
      </Link>
      <PageHeader title={data.name} subtitle={<span className="font-mono text-xs">{data.trace_id} · {data.source}</span>} />
      <TraceView trace={data} />
    </>
  )
}
