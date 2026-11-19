/**
 * Small inline-SVG charts. Marks follow the house specs: bars <= 24px with 4px rounded data
 * ends on a single baseline, 2px lines, >= 8px end markers with a surface ring, hairline
 * gridlines, one y-axis. Colors come from the validated --series-* tokens; text always uses
 * text tokens. Every chart has a hover tooltip and a table view (the light-theme series sit
 * below 3:1 contrast, so values must also be reachable without color).
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']

export function compact(n: number): string {
  const a = Math.abs(n)
  if (a >= 1e6) return `${+(n / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${+(n / 1e3).toFixed(1)}K`
  return n.toLocaleString(undefined, { maximumFractionDigits: a < 10 ? 2 : 0 })
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1]
  const raw = max / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks = []
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(+v.toFixed(10))
  if (ticks[ticks.length - 1] < max) ticks.push(+(ticks[ticks.length - 1] + step).toFixed(10))
  return ticks
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

/** Card with title, optional legend, and a Chart / Table toggle. */
export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  children,
  empty,
  actions,
}: {
  title: string
  subtitle?: string
  legend?: { name: string; color: string; kind?: 'line' | 'rect' }[]
  table: { head: string[]; rows: (string | number)[][] }
  children: ReactNode
  empty?: string
  actions?: ReactNode
}) {
  const [asTable, setAsTable] = useState(false)
  return (
    <section className="flex min-w-0 flex-col rounded-3xl bg-surface-container p-4">
      <header className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="text-xs text-on-surface-variant">{subtitle}</p>}
        </div>
        {actions && <div className="ml-auto shrink-0">{actions}</div>}
        <div className="flex shrink-0 rounded-full border border-outline-variant p-0.5 text-xs">
          {['Chart', 'Table'].map((m) => (
            <button
              key={m}
              onClick={() => setAsTable(m === 'Table')}
              aria-pressed={asTable === (m === 'Table')}
              className={`rounded-full px-2.5 py-0.5 ${asTable === (m === 'Table') ? 'bg-secondary-container font-medium text-on-secondary-container' : 'text-on-surface-variant'}`}
            >
              {m}
            </button>
          ))}
        </div>
      </header>
      {legend && legend.length > 1 && !asTable && (
        <ul className="mb-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-on-surface-variant">
          {legend.map((l) => (
            <li key={l.name} className="flex items-center gap-1.5">
              {l.kind === 'rect' ? (
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: l.color }} />
              ) : (
                <span className="h-0.5 w-3.5 rounded-full" style={{ background: l.color }} />
              )}
              {l.name}
            </li>
          ))}
        </ul>
      )}
      {empty ? (
        <p className="grid flex-1 place-items-center py-10 text-center text-sm text-on-surface-variant">{empty}</p>
      ) : asTable ? (
        <div className="max-h-72 overflow-auto rounded-xl border border-outline-variant">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-container-highest">
              <tr>
                {table.head.map((h) => (
                  <th key={h} className="px-2 py-1.5 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-t border-outline-variant">
                  {r.map((c, j) => (
                    <td key={j} className={`px-2 py-1 ${j > 0 ? 'tabular-nums' : ''}`}>
                      {typeof c === 'number' ? compact(c) : c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </section>
  )
}

function Tooltip({ x, y, children, width }: { x: number; y: number; children: ReactNode; width: number }) {
  const left = Math.min(Math.max(x + 12, 0), Math.max(width - 170, 0))
  return (
    <div
      className="pointer-events-none absolute z-10 min-w-[120px] rounded-xl border border-outline-variant bg-surface px-2.5 py-1.5 text-xs shadow-md"
      style={{ left, top: Math.max(y - 10, 0) }}
    >
      {children}
    </div>
  )
}

const PAD = { top: 10, right: 12, bottom: 24, left: 40 }

/** Vertical columns for one series over dates. */
export function ColumnChart({ data, color = SERIES[0], format = compact, height = 200, unit = '' }: {
  data: { x: string; y: number }[]
  color?: string
  format?: (n: number) => string
  height?: number
  unit?: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(0, ...data.map((d) => d.y))
  const ticks = niceTicks(max)
  const top = ticks[ticks.length - 1]
  const innerW = Math.max(width - PAD.left - PAD.right, 0)
  const innerH = height - PAD.top - PAD.bottom
  const band = data.length ? innerW / data.length : 0
  const barW = Math.min(24, Math.max(band - 2, 1)) // cap at 24px, keep a 2px gap between bars
  const y = (v: number) => PAD.top + innerH - (v / top) * innerH
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(Math.floor(innerW / 56), 1)))

  return (
    <div ref={ref} className="relative" onPointerLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Column chart">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} strokeWidth={1} />
              <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="var(--viz-muted)" className="tabular-nums">
                {format(t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = PAD.left + band * i + band / 2
            const h = Math.max(y(0) - y(d.y), d.y > 0 ? 1 : 0)
            const x0 = cx - barW / 2
            const r = Math.min(4, barW / 2, h)
            const yTop = y(0) - h
            const path = h > 0
              ? `M${x0},${y(0)} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x0 + barW - r} Q${x0 + barW},${yTop} ${x0 + barW},${yTop + r} V${y(0)} Z`
              : ''
            return (
              <g key={d.x}>
                {path && <path d={path} fill={color} opacity={hover === null || hover === i ? 1 : 0.55} />}
                {/* hit target: the whole band, not just the painted bar */}
                <rect
                  x={PAD.left + band * i}
                  y={PAD.top}
                  width={band}
                  height={innerH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${shortDate(d.x)}: ${format(d.y)}${unit}`}
                  onPointerEnter={() => setHover(i)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
                {i % labelEvery === 0 && (
                  <text x={cx} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                    {shortDate(d.x)}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && data[hover] && (
        <Tooltip x={PAD.left + band * hover + band / 2} y={y(data[hover].y)} width={width}>
          <div className="text-sm font-semibold">
            {format(data[hover].y)}
            {unit}
          </div>
          <div className="text-on-surface-variant">{shortDate(data[hover].x)}</div>
        </Tooltip>
      )}
    </div>
  )
}

/** Horizontal bars for ranked categories, value at the tip. */
export function HBarChart({ data, color = SERIES[0] }: { data: { label: string; value: number }[]; color?: string }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <ul className="space-y-2 py-1">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-3 text-xs" title={`${d.label}: ${d.value.toLocaleString()}`}>
          <span className="truncate text-on-surface-variant">{d.label}</span>
          <span className="flex items-center gap-2">
            <span className="h-3 rounded-r" style={{ width: `${Math.max((d.value / max) * 85, 0.5)}%`, background: color }} />
            <span className="tabular-nums">{compact(d.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

export interface LineSeries {
  name: string
  color: string
  points: { x: string; y: number | null }[]
}

/** Multi-series lines over shared dates, crosshair tooltip listing every series. */
export function LineChart({ series, dates, height = 220, format = compact, unit = '', max: fixedMax }: {
  series: LineSeries[]
  dates: string[]
  height?: number
  format?: (n: number) => string
  unit?: string
  max?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const values = series.flatMap((s) => s.points.map((p) => p.y).filter((v): v is number => v !== null))
  const ticks = niceTicks(fixedMax ?? Math.max(0, ...values))
  const top = ticks[ticks.length - 1]
  const innerW = Math.max(width - PAD.left - PAD.right, 0)
  const innerH = height - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (dates.length > 1 ? (i / (dates.length - 1)) * innerW : innerW / 2)
  const y = (v: number) => PAD.top + innerH - (v / top) * innerH
  const labelEvery = Math.max(1, Math.ceil(dates.length / Math.max(Math.floor(innerW / 56), 1)))

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    const rel = (e.clientX - box.left) / box.width
    setHover(Math.round(rel * (dates.length - 1)))
  }

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Line chart: ${series.map((s) => s.name).join(', ')}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--viz-axis)' : 'var(--viz-grid)'} strokeWidth={1} />
              <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={10} fill="var(--viz-muted)">
                {format(t)}
                {unit}
              </text>
            </g>
          ))}
          {dates.map(
            (d, i) =>
              i % labelEvery === 0 && (
                <text key={d} x={x(i)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                  {shortDate(d)}
                </text>
              ),
          )}
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--viz-axis)" strokeWidth={1} />}
          {series.map((s) => {
            const pts = s.points.map((p, i) => (p.y === null ? null : ([x(i), y(p.y)] as const)))
            let d = ''
            pts.forEach((p, i) => {
              if (!p) return
              d += `${d && pts[i - 1] ? 'L' : 'M'}${p[0]},${p[1]} `
            })
            const lastIdx = pts.map((p) => !!p).lastIndexOf(true)
            const marker = hover !== null && pts[hover] ? pts[hover] : lastIdx >= 0 ? pts[lastIdx] : null
            return (
              <g key={s.name}>
                <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {/* single points have no segment to draw, so always mark them */}
                {pts.map((p, i) => p && !pts[i - 1] && !pts[i + 1] && <circle key={i} cx={p[0]} cy={p[1]} r={4} fill={s.color} stroke="var(--md-surface-container)" strokeWidth={2} />)}
                {marker && <circle cx={marker[0]} cy={marker[1]} r={4} fill={s.color} stroke="var(--md-surface-container)" strokeWidth={2} />}
              </g>
            )
          })}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={innerW}
            height={innerH}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') setHover((h) => Math.min((h ?? -1) + 1, dates.length - 1))
              if (e.key === 'ArrowLeft') setHover((h) => Math.max((h ?? dates.length) - 1, 0))
            }}
            onBlur={() => setHover(null)}
            aria-label="Use arrow keys to read values by date"
          />
        </svg>
      )}
      {hover !== null && dates[hover] && (
        <Tooltip x={x(hover)} y={PAD.top} width={width}>
          <div className="mb-1 text-on-surface-variant">{shortDate(dates[hover])}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-2">
              <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} />
              <span className="font-semibold tabular-nums">{s.points[hover]?.y == null ? '—' : `${format(s.points[hover].y!)}${unit}`}</span>
              <span className="text-on-surface-variant">{s.name}</span>
            </div>
          ))}
        </Tooltip>
      )}
    </div>
  )
}

export function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-3xl bg-surface-container p-4">
      <div className="text-xs text-on-surface-variant">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-on-surface-variant">{sub}</div>}
    </div>
  )
}
