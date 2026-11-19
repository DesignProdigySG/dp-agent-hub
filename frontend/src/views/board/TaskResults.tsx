import { useEffect, useState } from 'react'

import { AttachmentList } from '../../components/Attachments'
import { Dialog } from '../../components/Dialog'
import { MarketoChanges, MarketoLink } from '../../components/MarketoLinks'
import { Markdown } from '../../components/Markdown'
import { Icon } from '../../components/ui'
import { useHub } from '../../store/hub'
import { Conversation } from './Conversation'
import { DesignResults, FeedbackBox } from './DesignResults'
import { HealthScanReport } from './HealthScanReport'
import { api, type DesignGroup, type MarketoChange, type WorkflowLogRow } from '../../lib/api'
import type { TaskOut } from '../../types/contract'

const TONE: Record<string, string> = {
  DONE: 'bg-primary-container text-on-primary-container',
  TRIGGERED: 'bg-primary-container text-on-primary-container',
  PENDING_APPROVAL: 'bg-tertiary-container text-on-tertiary-container',
  ERROR: 'bg-error-container text-error',
}

const isPlain = (v: unknown) => ['string', 'number', 'boolean'].includes(typeof v) && v !== ''

/** One item a workflow decided on (e.g. a lead): its status, score, output and outcome. */
function ItemResult({ row }: { row: WorkflowLogRow }) {
  const out = (row.data.output ?? {}) as Record<string, unknown>
  const approval = row.data.approval as { decision?: string; approver?: string; note?: string } | undefined
  const result = row.tool_result || row.status
  const facts = Object.entries(out).filter(([k, v]) => k !== 'summary' && (isPlain(v) || (Array.isArray(v) && v.length > 0)))
  return (
    <section className="space-y-3 rounded-2xl border border-outline-variant bg-surface p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold">{row.marketo_url ? `Lead ${row.item_id}` : row.item_id}</h3>
        {row.marketo_url && <MarketoLink href={row.marketo_url} className="text-xs" />}
        {row.action && <code className="rounded bg-surface-container-highest px-1.5 py-0.5 text-xs">{row.action}</code>}
        {row.score !== null && <span className="text-sm font-medium tabular-nums">{row.score} / 100</span>}
        <span className={`ml-auto rounded-full px-2 py-0.5 text-xs font-medium ${TONE[result] ?? 'bg-surface-container-highest'}`}>{result.replace(/_/g, ' ').toLowerCase()}</span>
      </header>
      {facts.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-on-surface-variant">{k}</dt>
              <dd className="min-w-0 break-words">{Array.isArray(v) ? v.join(', ') : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {typeof out.summary === 'string' && out.summary && <p className="text-sm">{out.summary}</p>}
      <ul className="space-y-1 text-xs text-on-surface-variant">
        {approval?.decision && <li>Decision: {approval.decision}{approval.approver ? ` by ${approval.approver}` : ''}{approval.note ? ` (“${approval.note}”)` : ''}</li>}
        {typeof row.data.campaign_id === 'number' && <li>Requested Marketo campaign {row.data.campaign_id}</li>}
        {typeof row.data.error === 'string' && <li className="text-error">{row.data.error}</li>}
      </ul>
    </section>
  )
}

/** Everything a task produced: per-item results for workflow agents, a scan report, design
 *  previews, or the agent's text; agent tasks also take feedback for another round. */
/** Who handed this task over, with a way to open the task it came from. */
function HandedOffBy({ task, onOpen }: { task: TaskOut; onOpen: (t: TaskOut) => void }) {
  const p = task.params as Record<string, unknown>
  const fromName = p?.from_agent_name as string | undefined
  const origin = useHub((s) => (p?.from_task_id ? s.tasks[p.from_task_id as string] : undefined))
  if (!fromName) return null
  return (
    <p className="flex items-center gap-1.5 rounded-xl bg-surface-container-high px-3 py-2 text-xs">
      <Icon name="swap_horiz" className="!text-[16px]" />
      <span>
        Handed off by <b>{fromName}</b>
        {origin && (
          <>
            {' '}from{' '}
            <button onClick={() => onOpen(origin)} className="font-medium text-primary underline-offset-2 hover:underline">
              {origin.title}
            </button>
          </>
        )}
      </span>
    </p>
  )
}

export function TaskResults({ task, onClose }: { task: TaskOut; onClose: () => void }) {
  const [origin, setOrigin] = useState<TaskOut | null>(null)
  const [rows, setRows] = useState<WorkflowLogRow[] | null>(null)
  const [designs, setDesigns] = useState<DesignGroup[]>([])
  const [marketo, setMarketo] = useState<{ changes: MarketoChange[]; links_configured: boolean }>({ changes: [], links_configured: true })
  const [error, setError] = useState('')
  const isAdmin = useHub((s) => s.auth.authenticated)
  const agent = useHub((s) => s.agents.find((a) => a.id === task.agent_id))
  useEffect(() => {
    api.taskLog(task.id).then(setRows).catch((e: Error) => setError(e.message))
    api.taskDesigns(task.id).then(setDesigns).catch(() => setDesigns([]))
    api.taskMarketo(task.id).then(setMarketo).catch(() => {})
  }, [task.id, task.status, task.updated_at])
  // A resumed item adds a second row for the same item; show the latest per item.
  const latest = rows ? [...new Map(rows.map((r) => [r.item_id, r])).values()] : []
  const scan = rows?.find((r) => r.data.kind === 'health_scan')?.data.scan_id as string | undefined
  const isWorkflow = Boolean(agent?.workflow || (task.params as Record<string, unknown>)?.workflow)
  const rounds = ((task.params as Record<string, unknown>)?.revisions as unknown[] | undefined)?.length ?? 0
  const canFeedback = isAdmin && !isWorkflow && (task.status === 'done' || task.status === 'failed')
  if (origin) return <TaskResults task={origin} onClose={() => setOrigin(null)} />
  return (
    <Dialog wide onClose={onClose} title={task.title}>
      <div className="space-y-3">
        {error && <p className="text-sm text-error">{error}</p>}
        <HandedOffBy task={task} onOpen={setOrigin} />
        <Conversation task={task} />
        {scan ? (
          <HealthScanReport scanId={scan} />
        ) : latest.length ? (
          latest.map((r) => <ItemResult key={r.id} row={r} />)
        ) : (
          rows && (
            <>
              <div className="rounded-2xl bg-surface p-4 text-sm">
                {rounds > 0 && <p className="mb-2 text-xs text-on-surface-variant">After feedback round {rounds}:</p>}
                {task.status === 'queued' || task.status === 'in_progress' ? 'Working on it…' : <Markdown text={task.result || 'No result yet.'} />}
              </div>
              {designs.length > 0 && <DesignResults groups={designs} />}
            </>
          )
        )}
        <MarketoChanges changes={marketo.changes} linksConfigured={marketo.links_configured} />
        <AttachmentList taskId={task.id} canEdit={isAdmin} />
        {canFeedback && !scan && !latest.length && <FeedbackBox taskId={task.id} onSent={onClose} />}
      </div>
    </Dialog>
  )
}
