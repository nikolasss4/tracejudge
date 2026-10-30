import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

/** A pointer-following tooltip rendered in a fixed layer, kept inside the viewport. */
export function FloatingTip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: x + 14, top: y + 14 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    let left = x + 14
    let top = y + 14
    if (left + width > window.innerWidth - 8) left = x - width - 14
    if (top + height > window.innerHeight - 8) top = y - height - 14
    setPos({ left: Math.max(8, left), top: Math.max(8, top) })
  }, [x, y])
  return (
    <div
      ref={ref}
      role="tooltip"
      className="pointer-events-none fixed z-50 max-w-xs rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs shadow-xl"
      style={pos}
    >
      {children}
    </div>
  )
}

export function TipRow({ color, label, value }: { color?: string; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-2 whitespace-nowrap">
      {color && <span className="h-0.5 w-3 rounded" style={{ background: color }} />}
      <span className="font-semibold text-[var(--ink)] tnum">{value}</span>
      <span className="text-[var(--ink-2)]">{label}</span>
    </div>
  )
}
