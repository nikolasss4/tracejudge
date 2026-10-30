import { Check, CornerUpLeft, SkipForward, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Transcript } from '../components/Transcript'
import { Empty, ErrorBox, PageHeader, Select } from '../components/ui'
import { api, type Calibration, type LabelQueue } from '../lib/api'
import { pct, runName } from '../lib/format'
import { useFetch } from '../lib/useFetch'

const OVERALL =
  'Should this trial pass overall? Judge the whole run: right actions, right answer, no policy violations. ' +
  'This calibrates the suite’s automated verdict (all deterministic checks plus judge criteria) against you.'

type Done = { result_id: string; criterion: string; human: boolean | null; verdict: boolean | null; case_id: string }

function CalibrationTable({ rows }: { rows: Calibration[] }) {
  if (rows.length === 0) return <p className="text-sm text-[var(--muted)]">No labels yet. Agreement and kappa appear here as you label.</p>
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-[var(--muted)]">
        <tr>
          <th className="py-1 font-normal">criterion</th>
          <th className="py-1 text-right font-normal">n</th>
          <th className="py-1 text-right font-normal">agree</th>
          <th className="py-1 text-right font-normal">κ</th>
          <th className="py-1 text-right font-normal" title="automated pass, human fail">too lenient</th>
          <th className="py-1 text-right font-normal" title="automated fail, human pass">too strict</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.criterion} className="border-t border-[var(--border)]/50">
            <td className="py-1.5 font-mono text-xs">{c.criterion}</td>
            <td className="py-1.5 text-right tnum">{c.n}</td>
            <td className="py-1.5 text-right tnum">{pct(c.agreement, 0)}</td>
            <td className="py-1.5 text-right tnum" title={c.kappa_band}>{c.kappa == null ? '–' : c.kappa.toFixed(2)}</td>
            <td className="py-1.5 text-right tnum">{c.confusion.judge_pass_human_fail}</td>
            <td className="py-1.5 text-right tnum">{c.confusion.judge_fail_human_pass}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function LabelPage() {
  const [params, setParams] = useSearchParams()
  const run = params.get('run') ?? ''
  const criterion = params.get('criterion') ?? ''
  const runs = useFetch(() => api.runs(), [])
  const [queue, setQueue] = useState<LabelQueue | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState<Done[]>([])
  const [note, setNote] = useState('')
  const noteRef = useRef<HTMLInputElement>(null)
  const cal = useFetch(() => (run ? api.calibration([run]) : Promise.resolve([])), [run, done.length])

  useEffect(() => {
    if (!run) return
    setQueue(null)
    setIndex(0)
    setDone([])
    api.labelQueue(run, criterion || undefined).then(setQueue, (e: Error) => setError(e.message))
  }, [run, criterion])

  const item = queue?.items[index]
  const detail = useFetch(() => (item ? api.result(item.result_id) : Promise.resolve(null)), [item?.result_id])
  const verdictOf = useCallback(
    (crit: string) => {
      const r = detail.data?.result
      if (!r) return null
      if (crit === 'overall') return r.passed
      return r.scores.find((s) => s.scorer === 'judge' && s.name === crit)?.passed ?? null
    },
    [detail.data],
  )

  const act = useCallback(
    async (human: boolean | null) => {
      if (!item) return
      if (human !== null) await api.label({ case_result_id: item.result_id, criterion: item.criterion, human_pass: human, note })
      setDone((d) => [...d, { result_id: item.result_id, criterion: item.criterion, human, verdict: verdictOf(item.criterion), case_id: item.case_id }])
      setNote('')
      setIndex((i) => i + 1)
    },
    [item, note, verdictOf],
  )

  const undo = useCallback(async () => {
    const last = done[done.length - 1]
    if (!last) return
    if (last.human !== null) await api.unlabel(last.result_id, last.criterion)
    setDone((d) => d.slice(0, -1))
    setIndex((i) => Math.max(0, i - 1))
  }, [done])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) {
        if (e.key === 'Escape') (e.target as HTMLElement).blur()
        if (e.key === 'Enter' && e.target === noteRef.current) noteRef.current?.blur()
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === 'p') act(true)
      else if (k === 'f') act(false)
      else if (k === 's') act(null)
      else if (k === 'u') undo()
      else if (k === 'n') {
        e.preventDefault()
        noteRef.current?.focus()
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [act, undo])

  const runOptions = [{ value: '', label: 'Pick a run…' }, ...(runs.data ?? []).map((r) => ({ value: r.run_id, label: `${runName(r)} · ${r.suite}` }))]
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next)
  }
  const last = done[done.length - 1]
  const desc = item && (item.criterion === 'overall' ? OVERALL : queue?.criteria.find((c) => c.name === item.criterion)?.description)
  const labelledNow = done.filter((d) => d.human !== null).length

  return (
    <>
      <PageHeader
        title="Label trials"
        subtitle="Your pass/fail labels calibrate the LLM judge and the suite's verdicts. The automated verdict stays hidden until you've labelled, so it can't anchor you."
      />
      <div className="mb-5 flex flex-wrap items-center gap-4">
        <Select label="Run" value={run} onChange={(v) => setParam('run', v)} options={runOptions} />
        {queue && (
          <Select
            label="Criterion"
            value={criterion}
            onChange={(v) => setParam('criterion', v)}
            options={[{ value: '', label: 'All criteria' }, { value: 'overall', label: 'overall' }, ...queue.criteria.map((c) => ({ value: c.name, label: c.name }))]}
          />
        )}
        <div className="ml-auto flex items-center gap-3 text-xs text-[var(--muted)]">
          <span><span className="kbd">P</span> pass</span>
          <span><span className="kbd">F</span> fail</span>
          <span><span className="kbd">S</span> skip</span>
          <span><span className="kbd">U</span> undo</span>
          <span><span className="kbd">N</span> note</span>
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      {!run && <Empty>Pick a run to label.</Empty>}
      {queue && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-4">
            <div className="flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--surface-3)]">
                <div className="h-full rounded-full bg-[var(--series-1)] transition-all" style={{ width: `${(index / Math.max(queue.items.length, 1)) * 100}%` }} />
              </div>
              <span className="text-xs text-[var(--ink-2)] tnum">{Math.min(index, queue.items.length)} / {queue.items.length} · {queue.labelled + labelledNow} labelled in this run</span>
            </div>
            {last && (
              <div className="card flex flex-wrap items-center gap-2 px-4 py-2 text-xs text-[var(--ink-2)]">
                Last: <span className="font-mono">{last.case_id} · {last.criterion}</span>
                {last.human === null ? (
                  'skipped'
                ) : (
                  <>
                    you <b className="text-[var(--ink)]">{last.human ? 'PASS' : 'FAIL'}</b>, automated <b className="text-[var(--ink)]">{last.verdict ? 'PASS' : 'FAIL'}</b>
                    {last.verdict === last.human ? (
                      <span className="inline-flex items-center gap-1 text-[var(--good-ink)]"><Check size={12} /> agree</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[var(--critical-ink)]"><X size={12} /> disagree</span>
                    )}
                  </>
                )}
              </div>
            )}
            {!item ? (
              <Empty>
                {queue.items.length === 0 ? 'Nothing left to label in this run.' : 'Queue finished.'}{' '}
                See the calibration table, or run <code className="font-mono">tracejudge calibrate</code>.
              </Empty>
            ) : detail.data ? (
              <>
                <section className="card p-4">
                  <div className="mb-3 flex flex-wrap items-baseline gap-2">
                    <Link to={`/results/${item.result_id}`} className="font-medium hover:underline">{item.case_id}</Link>
                    <span className="text-xs text-[var(--muted)]">trial {item.trial}</span>
                  </div>
                  <div className="mb-4 rounded-md bg-[var(--surface-2)] p-3 text-sm">
                    <div className="mb-1 text-[11px] uppercase tracking-wide text-[var(--muted)]">customer {detail.data.result.input?.customer_id}</div>
                    {detail.data.result.input?.message ?? JSON.stringify(detail.data.result.input)}
                  </div>
                  {detail.data.trace && <Transcript trace={detail.data.trace} />}
                </section>
              </>
            ) : null}
          </div>
          <aside className="space-y-4 xl:sticky xl:top-16 xl:self-start">
            {item && (
              <section className="card p-4">
                <div className="text-[11px] uppercase tracking-wide text-[var(--muted)]">criterion</div>
                <div className="mb-1 font-mono text-sm">{item.criterion}</div>
                <p className="mb-4 text-sm text-[var(--ink-2)]">{desc}</p>
                <input
                  ref={noteRef}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Optional note (why?)"
                  className="mb-3 w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1.5 text-sm outline-none focus:border-[var(--accent)]"
                />
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => act(true)} className="inline-flex items-center justify-center gap-1.5 rounded-md bg-[var(--good)] py-2 text-sm font-semibold text-[#0b0b0b] hover:brightness-110">
                    <Check size={16} strokeWidth={3} /> Pass <span className="kbd ml-1 border-black/20 bg-black/10 text-black/70">P</span>
                  </button>
                  <button type="button" onClick={() => act(false)} className="inline-flex items-center justify-center gap-1.5 rounded-md bg-[var(--critical)] py-2 text-sm font-semibold text-white hover:brightness-110">
                    <X size={16} strokeWidth={3} /> Fail <span className="kbd ml-1 border-white/20 bg-white/10 text-white/80">F</span>
                  </button>
                  <button type="button" onClick={() => act(null)} className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--border)] py-1.5 text-sm hover:bg-[var(--surface-2)]">
                    <SkipForward size={14} /> Skip
                  </button>
                  <button type="button" disabled={!done.length} onClick={undo} className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--border)] py-1.5 text-sm hover:bg-[var(--surface-2)] disabled:opacity-40">
                    <CornerUpLeft size={14} /> Undo
                  </button>
                </div>
                {detail.data && (
                  <div className="mt-4 border-t border-[var(--border)] pt-3">
                    <div className="text-[11px] uppercase tracking-wide text-[var(--muted)]">final answer</div>
                    <p className="mt-1 whitespace-pre-wrap text-sm">{String(detail.data.result.output ?? detail.data.result.error ?? '')}</p>
                  </div>
                )}
              </section>
            )}
            <section className="card p-4">
              <h2 className="mb-2 text-sm font-medium">Calibration for this run</h2>
              <CalibrationTable rows={cal.data ?? []} />
            </section>
          </aside>
        </div>
      )}
    </>
  )
}
