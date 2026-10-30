export type SpanKind = 'agent' | 'llm' | 'tool' | 'retrieval' | 'custom'

export interface Span {
  span_id: string
  trace_id: string
  parent_id: string | null
  name: string
  kind: SpanKind
  start_ns: number
  end_ns: number | null
  status: 'ok' | 'error'
  error: string | null
  input: unknown
  output: unknown
  attributes: Record<string, unknown>
  model: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
}

export interface Trace {
  trace_id: string
  name: string
  source: string
  start_ns: number
  end_ns: number | null
  run_id: string | null
  attributes: Record<string, unknown>
  spans: Span[]
}

export interface Summary {
  cases: number
  trials: number
  repeats: number
  pass_rate: number
  pass_rate_ci95: [number, number]
  pass_at_k: number
  pass_hat_k: number
  k: number
  flaky_cases: string[]
  flaky_rate: number
  cost_usd: number
  cost_per_trial_usd: number
  tokens: number
  latency_p50_ms: number
  latency_p95_ms: number
  mean_steps: number
  errors: number
  skipped_scores?: number
  top_failures: [string, number][]
  models?: Record<string, number>
}

export interface Run {
  run_id: string
  suite: string
  agent: string
  model: string | null
  label: string | null
  git_sha: string | null
  git_branch: string | null
  created_at: string
  finished_at: string | null
  status: string
  config: Record<string, any>
  summary: Summary
}

export interface Score {
  scorer: string
  name: string
  passed: boolean | null
  score: number | null
  reason: string
  details: Record<string, any>
}

export interface CaseResult {
  id: string
  run_id: string
  case_id: string
  trial: number
  trace_id: string | null
  input: any
  output: any
  error: string | null
  passed: boolean
  scores: Score[]
  latency_ms: number
  cost_usd: number
  input_tokens: number
  output_tokens: number
  steps: number
  tags: string[]
}

export interface TrialRef {
  id: string
  trial: number
  passed: boolean
  trace_id: string | null
  error: string | null
  latency_ms: number
  cost_usd: number
}

export interface CaseRow {
  case_id: string
  tags: string[]
  passed: number
  trials: number
  failing: string[]
  cost_usd: number
  latency_ms: number
  steps: number
  results: TrialRef[]
}

export interface RunDetail {
  run: Run
  cases: CaseRow[]
  trials: {
    id: string
    case_id: string
    trial: number
    passed: boolean
    latency_ms: number
    cost_usd: number
    tokens: number
    steps: number
  }[]
  labels: number
}

export interface Label {
  case_result_id: string
  criterion: string
  human_pass: boolean
  note: string
  labeler: string
  created_at: string
}

export interface ResultDetail {
  result: CaseResult
  trace: Trace | null
  labels: Label[]
}

export type CaseStatus =
  | 'regressed' | 'fixed' | 'degraded' | 'improved' | 'unchanged' | 'added' | 'removed'

export interface CaseDiff {
  case_id: string
  status: CaseStatus
  a_passed: number
  a_trials: number
  b_passed: number
  b_trials: number
  a_rate: number
  b_rate: number
  a_cost: number
  b_cost: number
  a_latency_ms: number
  b_latency_ms: number
  new_failures: string[]
  reasons: string[]
  trajectory_a: string[]
  trajectory_b: string[]
  diverged_at: number | null
  trial_a: string | null
  trial_b: string | null
  p_value: number | null
}

export interface Diff {
  a: Run
  b: Run
  pass_rate_a: number
  pass_rate_b: number
  pass_rate_delta: number
  p_value: number
  cost_per_trial_a: number
  cost_per_trial_b: number
  cost_change: number | null
  latency_p50_a: number
  latency_p50_b: number
  latency_p95_a: number
  latency_p95_b: number
  notes: string[]
  cases: CaseDiff[]
}

export interface Calibration {
  criterion: string
  n: number
  agreement: number | null
  kappa: number | null
  kappa_band: string
  confusion: Record<string, number>
  disagreements: {
    case_result_id: string
    case_id: string
    trial: number
    judge_pass: boolean
    human_pass: boolean
    judge_reason: string
    human_note: string
  }[]
}

export interface LabelQueue {
  run: Pick<Run, 'run_id' | 'suite' | 'label' | 'agent'>
  criteria: { name: string; description: string }[]
  items: { result_id: string; case_id: string; trial: number; criterion: string }[]
  labelled: number
}

export interface TraceSummary {
  trace_id: string
  name: string
  source: string
  start_ns: number
  end_ns: number | null
  run_id: string | null
  spans: number
  tokens: number
  cost_usd: number
  errors: number
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  runs: (q: Record<string, string> = {}) =>
    get<Run[]>(`/api/runs?${new URLSearchParams(q)}`),
  run: (id: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  result: (id: string) => get<ResultDetail>(`/api/results/${encodeURIComponent(id)}`),
  traces: () => get<TraceSummary[]>('/api/traces'),
  trace: (id: string) => get<Trace>(`/api/traces/${encodeURIComponent(id)}`),
  diff: (a: string, b: string) => get<Diff>(`/api/diff?${new URLSearchParams({ a, b })}`),
  labelQueue: (run: string, criterion?: string) =>
    get<LabelQueue>(
      `/api/label-queue?${new URLSearchParams(criterion ? { run, criterion } : { run })}`,
    ),
  calibration: (runs: string[] = []) =>
    get<Calibration[]>(`/api/calibration?${new URLSearchParams(runs.map((r) => ['run', r]))}`),
  async label(body: { case_result_id: string; criterion: string; human_pass: boolean; note: string }) {
    const r = await fetch('/api/labels', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(await r.text())
  },
  async unlabel(resultId: string, criterion: string) {
    await fetch(`/api/labels/${encodeURIComponent(resultId)}/${encodeURIComponent(criterion)}`, {
      method: 'DELETE',
    })
  },
}
