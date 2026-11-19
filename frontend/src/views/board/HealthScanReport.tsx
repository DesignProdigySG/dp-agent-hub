import { useEffect, useState } from 'react'

import { MarketoLink } from '../../components/MarketoLinks'
import { Button, Icon } from '../../components/ui'
import { api, HEALTH_DIMENSIONS, type DuplicateGroup, type HealthDimension, type HealthKpis, type HealthScan, type ScanLead } from '../../lib/api'
import { ChartFrame, HBarChart, SERIES, StatTile } from '../insights/charts'

const pct = (n: number, total: number) => (total ? `${Math.round((100 * n) / total)}%` : '0%')
const NOTE_LABELS: Record<string, string> = { dns: 'DNS check', ai_review: 'AI review', email_verification: 'Email verification', phone_verification: 'Phone verification' }
const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** Bars on a fixed 0-100 scale (scores and fill rates), value at the tip. */
function ScoreBars({ data }: { data: { label: string; value: number; hint?: string }[] }) {
  return (
    <ul className="space-y-2 py-1">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[minmax(0,10rem)_1fr] items-center gap-3 text-xs" title={d.hint ?? `${d.label}: ${d.value}`}>
          <span className="truncate text-on-surface-variant">{d.label}</span>
          <span className="flex items-center gap-2">
            <span className="h-3 w-[85%] overflow-hidden rounded-r bg-surface-container-highest">
              <span className="block h-full rounded-r" style={{ width: `${Math.max(d.value, 0.5)}%`, background: SERIES[0] }} />
            </span>
            <span className="w-8 tabular-nums">{Math.round(d.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

function Table({ head, rows, onRow }: { head: string[]; rows: (string | number)[][]; onRow?: (i: number) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-on-surface-variant">
            {head.map((h, i) => <th key={h} className={`px-2 py-1 font-medium ${i ? 'text-right' : ''}`}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-outline-variant ${onRow ? 'cursor-pointer hover:bg-surface-container-highest' : ''}`} onClick={onRow && (() => onRow(i))}>
              {r.map((c, j) => <td key={j} className={`px-2 py-1 ${j ? 'text-right tabular-nums' : ''}`}>{typeof c === 'number' ? c.toLocaleString() : c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Section({ title, children, subtitle }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl bg-surface-container p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {subtitle && <p className="text-xs text-on-surface-variant">{subtitle}</p>}
      <div className="mt-2">{children}</div>
    </section>
  )
}

function recommendations(report: string): string[] {
  const part = report.split('### Recommendations')[1]?.split('\n### ')[0] ?? ''
  return part.split('\n').map((l) => l.replace(/^\d+\.\s*/, '').trim()).filter(Boolean)
}

function Overview({ scan, onIssue }: { scan: HealthScan; onIssue: (code: string) => void }) {
  const k: HealthKpis = scan.kpis
  const t = k.total
  const c = k.contactability
  const recs = recommendations(scan.report)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Leads scanned" value={t.toLocaleString()} sub={scan.finished_at ? new Date(scan.finished_at).toLocaleString() : undefined} />
        <StatTile label="Overall health" value={`${Math.round(k.dimensions.overall.avg)}/100`} sub={`${pct(k.thresholds.overall_gt_70, t)} above 70`} />
        <StatTile label="Usable" value={pct(c.usable, t)} sub={`${c.usable.toLocaleString()} by email or phone`} />
        <StatTile label="Duplicates" value={k.duplicates.redundant.toLocaleString()} sub={`${k.duplicates.groups.toLocaleString()} groups to merge`} />
      </div>
      <ChartFrame
        title="Seven dimensions"
        subtitle="Average score per lead, 0-100"
        table={{ head: ['Dimension', 'Average', 'Leads at 80+', 'Weight'], rows: HEALTH_DIMENSIONS.map((d) => [title(d), Math.round(k.dimensions[d].avg), pct(k.dimensions[d].ge80, t), k.weights[d] ?? 0]) }}
      >
        <ScoreBars data={HEALTH_DIMENSIONS.map((d) => ({ label: title(d), value: k.dimensions[d].avg, hint: `${title(d)}: average ${k.dimensions[d].avg}; ${pct(k.dimensions[d].ge80, t)} of leads at 80+` }))} />
      </ChartFrame>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Can't be emailed" value={c.unreachable_email.toLocaleString()} sub={pct(c.unreachable_email, t)} />
        <StatTile label="Phone can't be right" value={c.invalid_phone.toLocaleString()} sub={pct(c.invalid_phone, t)} />
        <StatTile label="Free email only" value={c.free_email_only.toLocaleString()} sub={pct(c.free_email_only, t)} />
        <StatTile label="Email and phone" value={c.email_and_phone.toLocaleString()} sub={pct(c.email_and_phone, t)} />
      </div>
      {recs.length > 0 && (
        <Section title="Recommendations">
          <ol className="list-decimal space-y-1 pl-5 text-sm">{recs.map((r) => <li key={r}>{r}</li>)}</ol>
        </Section>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <ChartFrame title="Engagement" subtitle={`Opens, clicks, forms and visits over ${String(scan.params.engagement_months ?? 18)} months`} table={{ head: ['Level', 'Leads'], rows: Object.entries(k.engagement_levels).map(([l, n]) => [title(l), n]) }}>
          <HBarChart data={Object.entries(k.engagement_levels).map(([l, n]) => ({ label: title(l), value: n }))} />
        </ChartFrame>
        <ChartFrame title="Relevant fields filled" subtitle="% of leads" table={{ head: ['Field', '% filled'], rows: Object.entries(k.field_fill).map(([f, v]) => [f, v]) }}>
          <ScoreBars data={Object.entries(k.field_fill).map(([f, v]) => ({ label: f, value: v }))} />
        </ChartFrame>
      </div>
      <Section title="Most common problems" subtitle="Select a row to see those leads">
        <Table head={['Problem', 'Dimension', 'Leads', '% of leads']} rows={k.issues.slice(0, 15).map((i) => [i.label, i.dim, i.leads, pct(i.leads, t)])} onRow={(i) => onIssue(k.issues[i].code)} />
      </Section>
      {k.sources.length > 0 && (
        <Section title="Where problems come from" subtitle="By lead source">
          <Table head={['Source', 'Leads', 'Duplicates', 'Accuracy < 80', 'Avg health']} rows={k.sources.map((s) => [s.source, s.leads, s.duplicates, s.low_accuracy, Math.round(s.overall)])} />
        </Section>
      )}
      {k.cohorts.length > 0 && (
        <Section title="By year created" subtitle="Is newer data better or worse?">
          <Table head={['Year', 'Leads', 'Completeness', 'Accuracy', 'Health']} rows={k.cohorts.map((x) => [String(x.year), x.leads, Math.round(x.completeness), Math.round(x.accuracy), Math.round(x.overall)])} />
        </Section>
      )}
      <Section title="How this scan ran">
        <ul className="space-y-0.5 text-xs text-on-surface-variant">
          <li>Leads read: {Number(scan.counts.leads ?? t).toLocaleString()} · activities read: {Number(scan.counts.activities ?? 0).toLocaleString()} ({String(scan.counts.activity_source ?? 'bulk')})</li>
          {Object.entries(k.notes).filter(([n]) => !n.startsWith('activity_')).map(([n, v]) => <li key={n}>{NOTE_LABELS[n] ?? title(n.replace(/_/g, ' '))}: {v}</li>)}
        </ul>
      </Section>
    </div>
  )
}

function LeadRow({ row }: { row: ScanLead }) {
  const [open, setOpen] = useState(false)
  const l = row.lead
  const name = [l.firstName, l.lastName].filter(Boolean).join(' ') || `Lead ${row.lead_id}`
  return (
    <li className="rounded-2xl border border-outline-variant bg-surface p-3">
      <button className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left" onClick={() => setOpen(!open)}>
        <span className="font-medium">{name}</span>
        <span className="min-w-0 truncate text-xs text-on-surface-variant">{[l.email, l.company].filter(Boolean).join(' · ')}</span>
        <span className="ml-auto text-sm font-semibold tabular-nums">{row.scores.overall}</span>
        <Icon name={open ? 'expand_less' : 'expand_more'} className="!text-[18px] text-on-surface-variant" />
      </button>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] tabular-nums text-on-surface-variant">
        {HEALTH_DIMENSIONS.map((d) => <span key={d}>{title(d).slice(0, 5)} {row.scores[d]}</span>)}
        <span>· {row.engagement_level}</span>
        <span>· reach: {row.reach || 'none'}</span>
      </div>
      {open && (
        <ul className="mt-2 space-y-0.5 text-xs">
          <li className="text-on-surface-variant">
            Marketo lead {row.lead_id}
            {l.leadSource ? ` · source ${l.leadSource}` : ''}
            {row.marketo_url && (
              <>
                {' · '}
                <MarketoLink href={row.marketo_url} />
              </>
            )}
          </li>
          {row.issues.length ? row.issues.map((i, n) => (
            <li key={n}>
              <span className="text-on-surface-variant">{i.dim}:</span> {i.message}
            </li>
          )) : <li>No problems found.</li>}
        </ul>
      )}
    </li>
  )
}

function Leads({ scanId, issue, issueLabel, clearIssue }: { scanId: string; issue: string; issueLabel?: string; clearIssue: () => void }) {
  const [sort, setSort] = useState<HealthDimension | 'overall'>('overall')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<{ total: number; rows: ScanLead[] } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.healthScanLeads(scanId, { sort, issue: issue || undefined, offset }).then(setData).catch((e: Error) => setError(e.message))
  }, [scanId, sort, issue, offset])
  useEffect(() => setOffset(0), [sort, issue])
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-2">
          Worst first by
          <select className="rounded-lg border border-outline-variant bg-surface px-2 py-1" value={sort} onChange={(e) => setSort(e.target.value as HealthDimension)}>
            {(['overall', ...HEALTH_DIMENSIONS] as const).map((d) => <option key={d} value={d}>{title(d)}</option>)}
          </select>
        </label>
        {issue && (
          <button className="flex items-center gap-1 rounded-full bg-secondary-container px-2 py-0.5 text-xs text-on-secondary-container" onClick={clearIssue}>
            {issueLabel ?? issue} <Icon name="close" className="!text-[14px]" />
          </button>
        )}
        {data && <span className="ml-auto text-xs text-on-surface-variant">{data.total.toLocaleString()} leads</span>}
      </div>
      {error && <p className="text-sm text-error">{error}</p>}
      <ul className="space-y-2">{data?.rows.map((r) => <LeadRow key={r.lead_id} row={r} />)}</ul>
      {data && data.total > 25 && (
        <div className="flex items-center justify-end gap-2 text-xs">
          <Button variant="text" className="!h-8 !px-2" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}><Icon name="chevron_left" /></Button>
          <span className="tabular-nums">{offset + 1}-{Math.min(offset + 25, data.total)} of {data.total.toLocaleString()}</span>
          <Button variant="text" className="!h-8 !px-2" disabled={offset + 25 >= data.total} onClick={() => setOffset(offset + 25)}><Icon name="chevron_right" /></Button>
        </div>
      )}
    </div>
  )
}

function Duplicates({ scanId }: { scanId: string }) {
  const [data, setData] = useState<{ total: number; groups: DuplicateGroup[] } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.healthScanDuplicates(scanId).then(setData).catch((e: Error) => setError(e.message))
  }, [scanId])
  if (error) return <p className="text-sm text-error">{error}</p>
  if (!data) return null
  if (!data.total) return <p className="text-sm text-on-surface-variant">No duplicates found.</p>
  return (
    <div className="space-y-2">
      <p className="text-xs text-on-surface-variant">{data.total.toLocaleString()} groups{data.total > data.groups.length ? `, first ${data.groups.length} shown` : ''}. The first record in each group is the one to keep: the most complete, then the most recently updated.</p>
      {data.groups.map((g) => (
        <ul key={g.group} className="rounded-2xl border border-outline-variant bg-surface p-3 text-sm">
          {g.members.map((m) => (
            <li key={m.lead_id} className="flex flex-wrap items-center gap-x-3">
              <Icon name={m.role === 'survivor' ? 'star' : 'content_copy'} className="!text-[16px] text-on-surface-variant" />
              <span className="font-medium">{[m.lead.firstName, m.lead.lastName].filter(Boolean).join(' ') || `Lead ${m.lead_id}`}</span>
              <span className="text-xs text-on-surface-variant">{[m.lead.email, m.lead.company].filter(Boolean).join(' · ')}</span>
              <span className="ml-auto flex items-center gap-1 text-xs text-on-surface-variant">
                #{m.lead_id} · {m.role === 'survivor' ? 'keep' : 'merge'} · {m.completeness}% complete
                {m.marketo_url && <MarketoLink href={m.marketo_url}>Open</MarketoLink>}
              </span>
            </li>
          ))}
          <li className="mt-1 text-xs text-on-surface-variant">Matched on {g.members.find((m) => m.matched_on)?.matched_on}</li>
        </ul>
      ))}
    </div>
  )
}

/** A data health scan's results: KPIs, then the leads and duplicates behind them. */
export function HealthScanReport({ scanId }: { scanId: string }) {
  const [scan, setScan] = useState<HealthScan | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'overview' | 'leads' | 'duplicates'>('overview')
  const [issue, setIssue] = useState('')
  useEffect(() => {
    api.healthScan(scanId).then(setScan).catch((e: Error) => setError(e.message))
  }, [scanId])
  if (error) return <p className="text-sm text-error">{error}</p>
  if (!scan) return <p className="text-sm text-on-surface-variant">Loading scan...</p>
  if (scan.status !== 'done') return <p className="text-sm">Scan {scan.status} in its {scan.phase} phase. {scan.error}</p>
  const tabs = [['overview', 'Overview'], ['leads', 'Leads'], ['duplicates', 'Duplicates']] as const
  return (
    <div className="space-y-3">
      <nav className="flex gap-1">
        {tabs.map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)} className={`rounded-full px-3 py-1 text-sm ${tab === id ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant hover:bg-surface-container-highest'}`}>
            {label}
          </button>
        ))}
      </nav>
      {tab === 'overview' && <Overview scan={scan} onIssue={(code) => { setIssue(code); setTab('leads') }} />}
      {tab === 'leads' && <Leads scanId={scanId} issue={issue} issueLabel={scan.kpis.issues.find((i) => i.code === issue)?.label} clearIssue={() => setIssue('')} />}
      {tab === 'duplicates' && <Duplicates scanId={scanId} />}
    </div>
  )
}
