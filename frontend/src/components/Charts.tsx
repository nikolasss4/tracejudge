import { useEffect, useRef, useState, type ReactNode } from 'react'
import { FloatingTip, TipRow } from './Tooltip'

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(600)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

/** Axis top and tick step: a 1/2/5 step with at most 5 intervals, top a whole number of steps. */
function niceScale(v: number): { max: number; step: number } {
  if (v <= 0) return { max: 1, step: 0.25 }
  const raw = v / 4
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((m) => m >= raw) ?? raw
  return { max: Math.ceil(v / step - 1e-9) * step, step }
}
function niceMax(v: number) {
  return niceScale(v).max
}

const M = { top: 12, right: 16, bottom: 28, left: 52 }

export function ChartCard({ title, subtitle, children, legend }: { title: string; subtitle?: string; children: ReactNode; legend?: ReactNode }) {
  return (
    <section className="card min-w-0 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">{title}</h2>
          {subtitle && <p className="text-xs text-[var(--muted)]">{subtitle}</p>}
        </div>
        {legend}
      </div>
      {children}
    </section>
  )
}

export function Legend({ items, shape = 'line' }: { items: { label: string; color: string }[]; shape?: 'line' | 'rect' }) {
  return (
    <div className="flex flex-wrap gap-3 text-xs text-[var(--ink-2)]">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className={shape === 'line' ? 'h-0.5 w-4 rounded' : 'h-2.5 w-2.5 rounded-sm'} style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  )
}

function YAxis({ max, h, w, fmt }: { max: number; h: number; w: number; fmt: (v: number) => string }) {
  const { step } = niceScale(max)
  const ticks: number[] = []
  for (let t = 0; t <= max + step / 1e6; t += step) ticks.push(t)
  return (
    <g>
      {ticks.map((t) => {
        const y = M.top + (1 - t / max) * h
        return (
          <g key={t}>
            <line x1={M.left} x2={w - M.right} y1={y} y2={y} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} strokeWidth={1} />
            <text x={M.left - 8} y={y} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--muted)" className="tnum">
              {fmt(t)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

/** Columns from a shared baseline: ≤24px wide, 4px rounded tops, per-bar hover. */
export function ColumnChart({
  data,
  fmt,
  height = 200,
  color = 'var(--series-1)',
  valueLabel,
}: {
  data: { label: string; value: number; sub?: string }[]
  fmt: (v: number) => string
  height?: number
  color?: string
  valueLabel: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [tip, setTip] = useState<{ i: number; x: number; y: number } | null>(null)
  const h = height - M.top - M.bottom
  const max = niceMax(Math.max(...data.map((d) => d.value), 0))
  const band = (width - M.left - M.right) / Math.max(data.length, 1)
  const bw = Math.min(24, band * 0.6)
  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={`${valueLabel} by run`}>
        <YAxis max={max} h={h} w={width} fmt={fmt} />
        {data.map((d, i) => {
          const bh = Math.max((d.value / max) * h, d.value > 0 ? 1 : 0)
          const x = M.left + band * i + (band - bw) / 2
          const y = M.top + h - bh
          const r = Math.min(4, bh)
          const path = `M${x},${M.top + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${M.top + h}Z`
          return (
            <g key={i} onPointerMove={(e) => setTip({ i, x: e.clientX, y: e.clientY })} onPointerLeave={() => setTip(null)}>
              <rect x={M.left + band * i} y={M.top} width={band} height={h} fill="transparent" />
              <path d={path} fill={color} opacity={tip && tip.i !== i ? 0.55 : 1} />
              <text x={x + bw / 2} y={M.top + h + 16} textAnchor="middle" fontSize={11} fill="var(--muted)">
                {d.label.length > 10 ? d.label.slice(0, 9) + '…' : d.label}
              </text>
            </g>
          )
        })}
        {data.length > 0 && (() => {
          const i = data.length - 1
          const d = data[i]
          const x = M.left + band * i + band / 2
          const y = M.top + h - (d.value / max) * h - 6
          return <text x={x} y={y} textAnchor="middle" fontSize={11} fill="var(--ink-2)" className="tnum">{fmt(d.value)}</text>
        })()}
      </svg>
      {tip && (
        <FloatingTip x={tip.x} y={tip.y}>
          <TipRow color={color} value={fmt(data[tip.i].value)} label={valueLabel} />
          <div className="mt-1 text-[var(--muted)]">{data[tip.i].label}{data[tip.i].sub ? ` · ${data[tip.i].sub}` : ''}</div>
        </FloatingTip>
      )}
    </div>
  )
}

/** Several series on one axis with a snapping crosshair and an all-series readout. */
export function LineChart({
  labels,
  series,
  fmt,
  height = 200,
}: {
  labels: string[]
  series: { name: string; color: string; values: number[] }[]
  fmt: (v: number) => string
  height?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null)
  const h = height - M.top - M.bottom
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)))
  const n = labels.length
  const x = (i: number) => (n <= 1 ? (M.left + width - M.right) / 2 : M.left + 8 + (i * (width - M.left - M.right - 16)) / (n - 1))
  const y = (v: number) => M.top + (1 - v / max) * h
  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={series.map((s) => s.name).join(' and ') + ' by run'}
        onPointerMove={(e) => {
          const px = e.clientX - e.currentTarget.getBoundingClientRect().left
          let best = 0
          for (let i = 0; i < n; i++) if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i
          setHover({ i: best, x: e.clientX, y: e.clientY })
        }}
        onPointerLeave={() => setHover(null)}
      >
        <YAxis max={max} h={h} w={width} fmt={fmt} />
        {labels.map((l, i) => (
          <text key={i} x={x(i)} y={M.top + h + 16} textAnchor="middle" fontSize={11} fill="var(--muted)">
            {l.length > 10 ? l.slice(0, 9) + '…' : l}
          </text>
        ))}
        {hover && <line x1={x(hover.i)} x2={x(hover.i)} y1={M.top} y2={M.top + h} stroke="var(--axis)" strokeWidth={1} />}
        {series.map((s) => (
          <g key={s.name}>
            <path
              d={s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join('')}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {s.values.map((v, i) =>
              i === n - 1 || hover?.i === i ? (
                <circle key={i} cx={x(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
              ) : null,
            )}
          </g>
        ))}
      </svg>
      {hover && (
        <FloatingTip x={hover.x} y={hover.y}>
          <div className="mb-1 text-[var(--muted)]">{labels[hover.i]}</div>
          {series.map((s) => (
            <TipRow key={s.name} color={s.color} value={fmt(s.values[hover.i])} label={s.name} />
          ))}
        </FloatingTip>
      )}
    </div>
  )
}

/** Distribution of trial latencies, bins separated by a 2px surface gap. */
export function Histogram({ values, fmt, bins = 20, height = 200 }: { values: number[]; fmt: (v: number) => string; bins?: number; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [tip, setTip] = useState<{ i: number; x: number; y: number } | null>(null)
  if (values.length === 0) return <div ref={ref} className="py-10 text-center text-sm text-[var(--muted)]">No trials.</div>
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const step = (hi - lo) / bins || 1
  const counts = Array.from({ length: bins }, () => 0)
  values.forEach((v) => counts[Math.min(bins - 1, Math.floor((v - lo) / step))]++)
  const h = height - M.top - M.bottom
  const max = niceMax(Math.max(...counts))
  const bw = (width - M.left - M.right) / bins
  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label="latency histogram">
        <YAxis max={max} h={h} w={width} fmt={(v) => String(Math.round(v))} />
        {counts.map((c, i) => {
          const bh = (c / max) * h
          const xx = M.left + i * bw + 1
          const yy = M.top + h - bh
          const r = Math.min(4, bh)
          const w2 = Math.max(bw - 2, 1)
          return (
            <g key={i} onPointerMove={(e) => setTip({ i, x: e.clientX, y: e.clientY })} onPointerLeave={() => setTip(null)}>
              <rect x={M.left + i * bw} y={M.top} width={bw} height={h} fill="transparent" />
              {c > 0 && (
                <path
                  d={`M${xx},${M.top + h}V${yy + r}Q${xx},${yy} ${xx + r},${yy}H${xx + w2 - r}Q${xx + w2},${yy} ${xx + w2},${yy + r}V${M.top + h}Z`}
                  fill="var(--series-1)"
                  opacity={tip && tip.i !== i ? 0.55 : 1}
                />
              )}
            </g>
          )
        })}
        {[0, Math.floor(bins / 2), bins].map((i) => (
          <text key={i} x={M.left + i * bw} y={M.top + h + 16} textAnchor="middle" fontSize={11} fill="var(--muted)" className="tnum">
            {fmt(lo + i * step)}
          </text>
        ))}
      </svg>
      {tip && (
        <FloatingTip x={tip.x} y={tip.y}>
          <TipRow color="var(--series-1)" value={`${counts[tip.i]} trials`} label={`${fmt(lo + tip.i * step)} – ${fmt(lo + (tip.i + 1) * step)}`} />
        </FloatingTip>
      )}
    </div>
  )
}
