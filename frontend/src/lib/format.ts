export const pct = (x: number | null | undefined, digits = 1) =>
  x == null || Number.isNaN(x) ? '–' : `${(x * 100).toFixed(digits)}%`

export const pts = (x: number) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)} pts`

export function usd(x: number | null | undefined) {
  if (x == null) return '–'
  if (x === 0) return '$0'
  if (x < 0.01) return `$${x.toFixed(4)}`
  if (x < 10) return `$${x.toFixed(3)}`
  return `$${x.toFixed(2)}`
}

export function ms(x: number | null | undefined) {
  if (x == null) return '–'
  if (x === 0) return '0'
  if (x < 1) return `${x.toFixed(2)} ms`
  if (x < 1000) return `${Math.round(x)} ms`
  return `${(x / 1000).toFixed(x < 10_000 ? 2 : 1)} s`
}

export function compact(n: number) {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K`
  return String(Math.round(n))
}

export const rel = (a: number, b: number) =>
  a ? `${b >= a ? '+' : ''}${(((b - a) / a) * 100).toFixed(0)}%` : 'n/a'

export function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export const runName = (r: { label: string | null; run_id: string }) => r.label ?? r.run_id

export const shortSha = (sha: string | null) => (sha ? sha.slice(0, 7) : '')

export function preview(v: unknown, max = 120): string {
  if (v == null) return ''
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s.length > max ? s.slice(0, max) + '…' : s
}
