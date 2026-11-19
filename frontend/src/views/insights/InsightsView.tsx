import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button, Icon, relativeTime } from '../../components/ui'
import { api, type ActivitySummary, type KpiRow, type LlmUsage, type RecentActivity } from '../../lib/api'
import { useHub } from '../../store/hub'
import { ChartFrame, ColumnChart, compact, HBarChart, LineChart, SERIES, StatTile, type LineSeries } from './charts'

const RANGES = [7, 30, 90] as const

function dateRange(days: number): string[] {
  const out: string[] = []
  const today = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i))
    out.push(d.toISOString().slice(0, 10))
  }
  return out
}

// Counters every run reports, or the snapshot adds; not KPIs an agent chose to track.
const RUN_COUNTERS = new Set(['runs', 'failed_runs', 'steps', 'tool_calls'])
const label = (k: string) => k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const pctFmt = (n: number) => `${+n.toFixed(1)}`

function kpiSeries(rows: KpiRow[], dates: string[], defs: { agent: string; metric: string; name: string }[]): LineSeries[] {
  const idx = new Map(rows.filter((r) => r.scope === 'agent').map((r) => [`${r.date}|${r.scope_id}|${r.metric}`, r.value]))
  return defs.map((d, i) => ({
    name: d.name,
    color: SERIES[i],
    points: dates.map((date) => ({ x: date, y: idx.get(`${date}|${d.agent}|${d.metric}`) ?? null })),
  }))
}

/** Runs per day, one series per agent in roster order; past four, the rest fold into "Other". */
function runSeries(rows: KpiRow[], dates: string[], agents: { id: string; name: string }[]): LineSeries[] {
  const runs = rows.filter((r) => r.scope === 'agent' && r.metric === 'runs')
  const active = agents.filter((a) => runs.some((r) => r.scope_id === a.id))
  const shown = active.length > SERIES.length ? active.slice(0, SERIES.length - 1) : active
  const groups = shown.map((a) => ({ name: a.name, ids: new Set([a.id]) }))
  if (shown.length < active.length) groups.push({ name: 'Other', ids: new Set(active.slice(shown.length).map((a) => a.id)) })
  return groups.map((g, i) => ({
    name: g.name,
    color: SERIES[i],
    points: dates.map((date) => {
      const day = runs.filter((r) => r.date === date && g.ids.has(r.scope_id))
      return { x: date, y: day.length ? day.reduce((a, r) => a + (r.value ?? 0), 0) : 0 }
    }),
  }))
}

/** Percentage KPIs an agent reports (values like "92.5%"), up to four. */
function percentMetrics(rows: KpiRow[], agentId: string): string[] {
  const names = new Set(rows.filter((r) => r.scope === 'agent' && r.scope_id === agentId && !RUN_COUNTERS.has(r.metric) && r.text?.trim().endsWith('%')).map((r) => r.metric))
  return [...names].sort().slice(0, SERIES.length)
}

export default function InsightsView() {
  const isAdmin = useHub((s) => s.auth.authenticated)
  const agents = useHub((s) => s.agents)
  const [kpiAgent, setKpiAgent] = useState<string>('')
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const [acts, setActs] = useState<ActivitySummary | null>(null)
  const [kpis, setKpis] = useState<KpiRow[]>([])
  const [llm, setLlm] = useState<LlmUsage | null>(null)
  const [recent, setRecent] = useState<RecentActivity[]>([])
  const [loading, setLoading] = useState(false)
  const [snapshotMsg, setSnapshotMsg] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [a, k, r, l] = await Promise.all([
        api.activities(days),
        api.kpis(days),
        api.recentActivities(20),
        isAdmin ? api.llmUsage(days) : Promise.resolve(null),
      ])
      setActs(a)
      setKpis(k)
      setRecent(r)
      setLlm(l)
    } finally {
      setLoading(false)
    }
  }, [days, isAdmin])

  useEffect(() => {
    load().catch(() => undefined)
    const t = setInterval(() => load().catch(() => undefined), 60_000)
    return () => clearInterval(t)
  }, [load])

  const dates = useMemo(() => dateRange(days), [days])
  const perDay = useMemo(() => {
    const m = new Map((acts?.per_day ?? []).map((d) => [d.date, d.count]))
    return dates.map((x) => ({ x, y: m.get(x) ?? 0 }))
  }, [acts, dates])
  const runs = useMemo(() => runSeries(kpis, dates, agents), [kpis, dates, agents])
  const kpiAgents = useMemo(() => agents.filter((a) => percentMetrics(kpis, a.id).length), [agents, kpis])
  const kpiAgentId = kpiAgents.some((a) => a.id === kpiAgent) ? kpiAgent : (kpiAgents[0]?.id ?? '')
  const agentKpis = useMemo(
    () => kpiSeries(kpis, dates, percentMetrics(kpis, kpiAgentId).map((m) => ({ agent: kpiAgentId, metric: m, name: label(m) }))),
    [kpis, dates, kpiAgentId],
  )
  const tasksDone = useMemo(() => {
    const m = new Map(kpis.filter((r) => r.scope === 'tasks' && r.metric === 'done').map((r) => [r.date, r.value ?? 0]))
    return dates.map((x) => ({ x, y: m.get(x) ?? 0 }))
  }, [kpis, dates])
  const spend = useMemo(() => {
    const m = new Map((llm?.per_day ?? []).map((d) => [d.date, d.cost_usd]))
    return dates.map((x) => ({ x, y: m.get(x) ?? 0 }))
  }, [llm, dates])

  const hasSnapshots = kpis.length > 0
  const noSnapshots = hasSnapshots ? undefined : 'No daily snapshots yet. They are taken automatically each day; use “Snapshot now” to capture today.'
  const lineTable = (series: LineSeries[]) => ({
    head: ['Date', ...series.map((s) => s.name)],
    rows: dates.filter((_, i) => series.some((s) => s.points[i].y !== null)).map((d) => [d, ...series.map((s) => s.points[dates.indexOf(d)].y ?? '—')]),
  })

  const snapshotNow = async () => {
    try {
      const r = await api.snapshotNow()
      setSnapshotMsg(`Captured ${r.metrics} metrics for ${r.date}`)
      await load()
    } catch (e) {
      setSnapshotMsg((e as Error).message)
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      {/* filters: one row, above everything they scope */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-full border border-outline-variant p-0.5 text-sm" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={`rounded-full px-3 py-1 ${days === r ? 'bg-secondary-container font-medium text-on-secondary-container' : 'text-on-surface-variant'}`}
            >
              Last {r} days
            </button>
          ))}
        </div>
        {loading && <Icon name="progress_activity" className="animate-spin text-on-surface-variant" />}
        <span className="flex-1" />
        {snapshotMsg && <span className="text-xs text-on-surface-variant">{snapshotMsg}</span>}
        {isAdmin && (
          <Button variant="tonal" onClick={snapshotNow}>
            <Icon name="photo_camera" /> Snapshot now
          </Button>
        )}
      </div>

      <div className={`space-y-3 transition-opacity ${loading && acts ? 'opacity-70' : ''}`}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Activities" value={acts ? compact(acts.total) : '—'} sub={`last ${days} days`} />
          <StatTile label="Engaged leads" value={acts ? compact(acts.engaged_leads) : '—'} sub="distinct leads with activity" />
          <StatTile label="Tasks completed" value={compact(tasksDone.reduce((a, d) => a + d.y, 0))} sub="from daily snapshots" />
          {isAdmin ? (
            <StatTile label="LLM spend" value={llm ? `$${llm.total_cost_usd.toFixed(2)}` : '—'} sub={llm ? `${compact(llm.calls)} calls` : undefined} />
          ) : (
            <StatTile label="Top activity" value={acts?.by_type[0]?.type ?? '—'} sub={acts?.by_type[0] ? `${compact(acts.by_type[0].count)} events` : undefined} />
          )}
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <ChartFrame
            title="Activity volume"
            subtitle="Marketo activities ingested per day"
            table={{ head: ['Date', 'Activities'], rows: perDay.map((d) => [d.x, d.y]) }}
            empty={acts && acts.total === 0 ? 'No activities ingested in this range yet.' : undefined}
          >
            <ColumnChart data={perDay} />
          </ChartFrame>
          <ChartFrame
            title="Activity by type"
            subtitle={`Last ${days} days`}
            table={{ head: ['Type', 'Count'], rows: (acts?.by_type ?? []).map((t) => [t.type, t.count]) }}
            empty={acts && acts.by_type.length === 0 ? 'No activities yet.' : undefined}
          >
            <HBarChart data={(acts?.by_type ?? []).slice(0, 8).map((t) => ({ label: t.type, value: t.count }))} />
          </ChartFrame>

          <ChartFrame
            title="Agent runs"
            subtitle="Finished runs per day, by agent"
            legend={runs.map((s) => ({ name: s.name, color: s.color }))}
            table={lineTable(runs)}
            empty={noSnapshots ?? (runs.length ? undefined : 'No agent runs in this range yet.')}
          >
            <LineChart series={runs} dates={dates}/>
          </ChartFrame>
          <ChartFrame
            title="Agent KPIs"
            subtitle="Percentage KPIs the agent reports, at end of day (%)"
            legend={agentKpis.map((s) => ({ name: s.name, color: s.color }))}
            table={lineTable(agentKpis)}
            empty={noSnapshots ?? (kpiAgentId ? undefined : 'No agent has reported percentage KPIs yet.')}
            actions={
              kpiAgents.length > 1 && (
                <select aria-label="Agent" className="rounded-full border border-outline-variant bg-transparent px-2 py-0.5 text-xs" value={kpiAgentId} onChange={(e) => setKpiAgent(e.target.value)}>
                  {kpiAgents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              )
            }
          >
            <LineChart series={agentKpis} dates={dates} max={100} format={pctFmt} unit="%" />
          </ChartFrame>

          <ChartFrame title="Tasks completed" subtitle="Per day, all agents" table={{ head: ['Date', 'Done'], rows: tasksDone.map((d) => [d.x, d.y]) }} empty={noSnapshots}>
            <ColumnChart data={tasksDone} />
          </ChartFrame>
          {isAdmin && (
            <ChartFrame
              title="LLM spend"
              subtitle="USD per day across all models"
              table={{
                head: ['Model', 'Tier', 'Calls', 'Failures', 'Tokens in', 'Tokens out', 'Cost (USD)'],
                rows: (llm?.by_model ?? []).map((m) => [m.model, m.tier, m.calls, m.failures, m.input_tokens, m.output_tokens, m.cost_usd.toFixed(4)]),
              }}
              empty={llm && llm.calls === 0 ? 'No LLM calls in this range. Add an API key in Settings to enable the router.' : undefined}
            >
              <ColumnChart data={spend} format={(n) => `$${n < 1 ? n.toFixed(2) : compact(n)}`} />
            </ChartFrame>
          )}
        </div>

        <section className="rounded-3xl bg-surface-container p-4">
          <h3 className="mb-2 text-sm font-semibold">Latest activity</h3>
          {recent.length ? (
            <ul className="divide-y divide-outline-variant text-xs">
              {recent.map((a) => (
                <li key={a.id} className="flex items-center gap-3 py-1.5">
                  <span className="w-16 shrink-0 text-on-surface-variant">{relativeTime(a.occurred_at)}</span>
                  <span className="w-32 shrink-0 truncate font-medium">{a.type}</span>
                  <span className="min-w-0 flex-1 truncate">{a.asset ?? '—'}</span>
                  <span className="shrink-0 text-on-surface-variant">lead {a.lead_id ?? '—'}</span>
                  <span className="shrink-0 rounded bg-surface-container-highest px-1.5 text-[10px] uppercase text-on-surface-variant">{a.source}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-on-surface-variant">Nothing ingested yet.</p>
          )}
        </section>
      </div>
    </div>
  )
}
