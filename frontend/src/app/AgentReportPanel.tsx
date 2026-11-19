import { useEffect, useState } from 'react'

import { Markdown } from '../components/Markdown'
import { MarketoChanges } from '../components/MarketoLinks'
import { Icon, relativeTime } from '../components/ui'
import { api, type AgentReport, type ReportKpi } from '../lib/api'
import { useHub } from '../store/hub'

const TONE = (good: boolean | null) => (good === true ? 'text-success' : good === false ? 'text-error' : 'text-on-surface-variant')

function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) return null
  const w = 44
  const h = 14
  const min = Math.min(...points)
  const span = Math.max(...points) - min || 1
  const xy = points.map((v, i) => `${(i / (points.length - 1)) * w},${h - 1 - ((v - min) / span) * (h - 2)}`)
  return (
    <svg width={w} height={h} aria-hidden="true" className="shrink-0">
      <polyline points={xy.join(' ')} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function Delta({ k }: { k: ReportKpi }) {
  if (k.trend === null) return null
  if (k.trend === 'flat') return <span className="text-[11px] text-on-surface-variant">no change</span>
  return (
    <span className={`flex items-center text-[11px] font-medium ${TONE(k.good)}`} title={k.good === null ? undefined : k.good ? 'Better' : 'Worse'}>
      <Icon name={k.trend === 'up' ? 'arrow_upward' : 'arrow_downward'} className="!text-[13px]" />
      {k.change}
    </span>
  )
}

function KpiRow({ k, color }: { k: ReportKpi; color: string }) {
  const bar = k.unit === 'score' || k.unit === 'pct'
  return (
    <li className="space-y-1" title={k.help || undefined}>
      <div className="flex items-center gap-2 text-xs">
        <span className="min-w-0 flex-1 truncate text-on-surface-variant">{k.label}</span>
        <Sparkline points={k.series.map((p) => p.value)} color={color} />
        <Delta k={k} />
        <span className="w-12 text-right font-medium tabular-nums">{k.display}</span>
      </div>
      {bar && (
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-container-highest">
          <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.min(Math.max(k.value, 0), 100)}%`, background: color }} />
        </div>
      )}
    </li>
  )
}

function Stat({ label, value, prev }: { label: string; value: string; prev?: string }) {
  return (
    <div className="rounded-xl bg-surface-container-high px-2.5 py-2">
      <div className="text-[11px] text-on-surface-variant">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      {prev !== undefined && <div className="text-[10px] text-on-surface-variant">prev. week {prev}</div>}
    </div>
  )
}

/** The agent's standard report: what it last did, its KPIs vs a week earlier, activity. */
export function AgentReportPanel({ agentId, color }: { agentId: string; color: string }) {
  const [report, setReport] = useState<AgentReport | null>(null)
  const [error, setError] = useState('')
  // refetch when the agent finishes something
  const state = useHub((s) => s.statuses[agentId]?.state)
  const lastTask = useHub((s) =>
    Object.values(s.tasks)
      .filter((t) => t.agent_id === agentId)
      .reduce((m, t) => (t.updated_at > m ? t.updated_at : m), ''),
  )
  useEffect(() => {
    api.agentReport(agentId).then(setReport).catch((e: Error) => setError(e.message))
  }, [agentId, state, lastTask])

  if (error) return <p className="text-sm text-error">{error}</p>
  if (!report) return <div className="h-24 rounded-2xl bg-surface-container-high" />
  const a = report.activity
  return (
    <div className="space-y-4">
      <section className="rounded-2xl bg-surface-container-high px-3 py-2.5">
        <h3 className="mb-1 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
          Latest report
          {report.headline && <span className="font-normal normal-case tracking-normal">{relativeTime(report.headline.at)}</span>}
        </h3>
        <div className="text-sm">{report.headline ? <Markdown text={report.headline.text} /> : 'No finished runs yet.'}</div>
        {report.highlights.length > 0 && (
          <ul className="mt-2 space-y-1">
            {report.highlights.map((h) => (
              <li key={h.text} className={`flex gap-1.5 text-xs ${TONE(h.good)}`}>
                <Icon name={h.good === true ? 'trending_up' : h.good === false ? 'trending_down' : 'info'} className="!text-[15px]" />
                <span className={h.good === null ? '' : 'text-on-surface'}>{h.text}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 flex items-baseline justify-between text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
          KPIs
          {report.compare && <span className="font-normal normal-case tracking-normal">change {report.compare}</span>}
        </h3>
        {report.kpis.length ? (
          <ul className="space-y-2.5">
            {report.kpis.map((k) => (
              <KpiRow key={k.key} k={k} color={color} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-on-surface-variant">This agent's KPIs appear after its first reporting run.</p>
        )}
      </section>

      <MarketoChanges changes={report.marketo} title="In Marketo (last 7 days)" />

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">Last 7 days</h3>
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Tasks done" value={String(a.tasks_done)} prev={String(a.previous.tasks_done)} />
          <Stat label="Failed" value={String(a.tasks_failed)} prev={String(a.previous.tasks_failed)} />
          <Stat label="Approvals asked" value={String(a.approvals)} prev={String(a.previous.approvals)} />
          <Stat label="AI cost" value={`$${a.cost_usd.toFixed(2)}`} prev={`$${a.previous.cost_usd.toFixed(2)}`} />
        </div>
      </section>
    </div>
  )
}
