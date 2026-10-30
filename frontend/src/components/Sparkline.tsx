import { useState } from 'react'
import { FloatingTip, TipRow } from './Tooltip'

export interface SparkPoint {
  value: number
  label: string
  highlight?: boolean
}

/** Pass-rate history: 0–100% fixed scale, 2px line, end dot, nearest-point hover. */
export function Sparkline({
  points,
  width = 120,
  height = 32,
  format = (v: number) => `${(v * 100).toFixed(1)}%`,
}: {
  points: SparkPoint[]
  width?: number
  height?: number
  format?: (v: number) => string
}) {
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null)
  if (points.length === 0) return null
  const pad = 5
  const x = (i: number) =>
    points.length === 1 ? width / 2 : pad + (i * (width - 2 * pad)) / (points.length - 1)
  const y = (v: number) => pad + (1 - v) * (height - 2 * pad)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join('')
  const last = points.length - 1
  const hi = points.findIndex((p) => p.highlight)
  return (
    <span className="relative inline-block">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`pass rate history: ${points.map((p) => format(p.value)).join(', ')}`}
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          const px = e.clientX - rect.left
          let best = 0
          points.forEach((_, i) => {
            if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i
          })
          setHover({ i: best, x: e.clientX, y: e.clientY })
        }}
        onPointerLeave={() => setHover(null)}
      >
        <line x1={pad} x2={width - pad} y1={y(1)} y2={y(1)} stroke="var(--grid)" strokeWidth={1} />
        <line x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} stroke="var(--grid)" strokeWidth={1} />
        <path d={d} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover && (
          <line x1={x(hover.i)} x2={x(hover.i)} y1={0} y2={height} stroke="var(--axis)" strokeWidth={1} />
        )}
        {[...new Set([last, ...(hi >= 0 ? [hi] : []), ...(hover ? [hover.i] : [])])].map((i) => (
          <circle
            key={i}
            cx={x(i)}
            cy={y(points[i].value)}
            r={4}
            fill="var(--series-1)"
            stroke="var(--surface)"
            strokeWidth={2}
          />
        ))}
      </svg>
      {hover && (
        <FloatingTip x={hover.x} y={hover.y}>
          <TipRow color="var(--series-1)" value={format(points[hover.i].value)} label={points[hover.i].label} />
        </FloatingTip>
      )}
    </span>
  )
}
