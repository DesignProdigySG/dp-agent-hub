import { useState } from 'react'

import { Button, Icon, TASK_STATUS, formatWhen } from '../../components/ui'
import { api } from '../../lib/api'
import { useHub } from '../../store/hub'
import { pendingApprovalFor } from '../../store/reduce'
import type { TaskOut, TaskStatus } from '../../types/contract'
import { EditTaskDialog } from './EditTaskDialog'
import { RecurringPanel } from './RecurringPanel'
import { TaskResults } from './TaskResults'
import { plainText } from '../../components/Markdown'

const COLUMNS: { id: string; label: string; statuses: TaskStatus[] }[] = [
  { id: 'queued', label: 'Queued', statuses: ['queued'] },
  { id: 'in_progress', label: 'In progress', statuses: ['in_progress'] },
  { id: 'needs_approval', label: 'Needs approval', statuses: ['needs_approval'] },
  { id: 'done', label: 'Done', statuses: ['done', 'failed'] },
]

function TaskCard({ task }: { task: TaskOut }) {
  const agent = useHub((s) => s.agents.find((a) => a.id === task.agent_id))
  const status = useHub((s) => s.statuses[task.agent_id])
  const approval = useHub((s) => pendingApprovalFor(s.approvals, task.id))
  const [error, setError] = useState<string | null>(null)
  const [showResults, setShowResults] = useState(false)
  const [editing, setEditing] = useState(false)
  const st = TASK_STATUS[task.status]
  const finished = task.status === 'done' || task.status === 'failed'
  const settled = finished || task.status === 'queued' // i.e. not running or waiting
  const live = status?.task_id === task.id && task.status === 'in_progress'
  const due = task.scheduled_for && new Date(task.scheduled_for) > new Date()
  const fromName = (task.params as Record<string, unknown>)?.from_agent_name as string | undefined
  // a planned task waits for earlier ones: name the first still unfinished
  const waitingFor = useHub((s) => {
    const after = ((task.params as Record<string, unknown>)?.after as string[] | undefined) ?? []
    const open = after.map((id) => s.tasks[id]).find((t) => t && t.status !== 'done')
    return task.status === 'queued' && open ? open.title : null
  })

  const act = (fn: () => Promise<unknown>) => () => fn().catch((e: Error) => setError(e.message))

  return (
    <article
      className={`space-y-2 rounded-2xl border bg-surface p-3 shadow-sm ${
        task.status === 'needs_approval' ? 'border-error' : 'border-outline-variant'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium leading-snug">
          {task.title}
          {task.run > 0 && <span className="ml-1.5 rounded-full bg-surface-container-highest px-1.5 text-[10px] font-normal text-on-surface-variant">run {task.run + 1}</span>}
        </h3>
        <Icon name={st.icon} className={`${st.tone} ${task.status === 'in_progress' ? 'animate-spin' : ''}`} filled={task.status !== 'in_progress'} />
      </div>
      <div className="flex items-center gap-2 text-xs">
        {agent && (
          <button
            onClick={() => useHub.getState().selectAgent(agent.id)}
            className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 font-medium"
            style={{ background: `color-mix(in srgb, ${agent.color} 16%, transparent)`, color: agent.color }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: agent.color }} />
            {agent.name}
          </button>
        )}
        {fromName && (
          <button
            onClick={() => setShowResults(true)}
            title={`Handed off by ${fromName}: open to see where it came from`}
            className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-full bg-surface-container-highest px-2 py-0.5 text-[11px] text-on-surface-variant"
          >
            <Icon name="swap_horiz" className="!text-[13px]" /> From {fromName}
          </button>
        )}
        <span className="truncate text-on-surface-variant" title={waitingFor ? `Starts when “${waitingFor}” is done` : undefined}>
          {waitingFor ? `Waiting for: ${waitingFor}` : task.status === 'queued' ? (due ? formatWhen(task.scheduled_for) : 'Next up') : formatWhen(task.updated_at)}
        </span>
      </div>
      {live && <p className="text-xs text-primary">{status.status_text}</p>}
      {(task.status === 'done' || task.status === 'failed') && task.result && (
        <p className={`line-clamp-3 whitespace-pre-line text-xs ${task.status === 'failed' ? 'text-error' : 'text-on-surface-variant'}`}>
          {plainText(task.result)}
        </p>
      )}
      {error && <p className="text-xs text-error">{error}</p>}
      <div className="flex justify-end gap-1">
        {(task.status === 'done' || task.status === 'failed' || task.status === 'needs_approval') && (
          <Button variant="text" className="!h-8 !px-3" onClick={() => setShowResults(true)}>
            <Icon name="fact_check" /> Results
          </Button>
        )}
        {task.status === 'queued' && due && !task.archived_at && (
          <Button variant="text" className="!h-8 !px-3" onClick={act(() => api.runTaskNow(task.id))}>
            <Icon name="play_arrow" /> Run now
          </Button>
        )}
        {finished && !task.archived_at && (
          <Button variant="text" className="!h-8 !px-2" title="Run again: move back to queued for a fresh run" onClick={act(() => api.requeueTask(task.id))}>
            <Icon name="replay" />
          </Button>
        )}
        {settled && !task.archived_at && (
          <Button variant="text" className="!h-8 !px-2" title={finished ? 'Edit, or edit and run again' : 'Edit task'} onClick={() => setEditing(true)}>
            <Icon name="edit" />
          </Button>
        )}
        {settled && (
          <Button
            variant="text"
            className="!h-8 !px-2"
            title={task.archived_at ? 'Unarchive' : task.status === 'queued' ? 'Archive (it won’t run while archived)' : 'Archive'}
            onClick={act(() => (task.archived_at ? api.unarchiveTask(task.id) : api.archiveTask(task.id)))}
          >
            <Icon name={task.archived_at ? 'unarchive' : 'archive'} />
          </Button>
        )}
        {settled && (
          <Button variant="text" className="!h-8 !px-2" title="Delete task" onClick={act(() => api.deleteTask(task.id))}>
            <Icon name="delete" />
          </Button>
        )}
        {approval && (
          <Button variant="danger" className="!h-8 !px-3" onClick={() => useHub.getState().review(approval.id)}>
            <Icon name="rate_review" /> Review
          </Button>
        )}
      </div>
      {showResults && <TaskResults task={task} onClose={() => setShowResults(false)} />}
      {editing && <EditTaskDialog task={task} onClose={() => setEditing(false)} />}
    </article>
  )
}

function ArchivedPanel({ tasks }: { tasks: TaskOut[] }) {
  const [open, setOpen] = useState(false)
  if (!tasks.length) return null
  return (
    <section className="rounded-3xl bg-surface-container px-3 py-2">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-1 text-sm font-semibold">
        <Icon name="inventory_2" className="!text-[18px]" /> Archived
        <span className="rounded-full bg-surface-container-highest px-2 text-xs font-normal tabular-nums text-on-surface-variant">{tasks.length}</span>
        <Icon name={open ? 'expand_less' : 'expand_more'} className="ml-auto" />
      </button>
      {open && (
        <div className="mt-2 grid max-h-80 grid-cols-1 gap-2 overflow-y-auto md:grid-cols-2 xl:grid-cols-4">
          {[...tasks]
            .sort((a, b) => (b.archived_at ?? '').localeCompare(a.archived_at ?? ''))
            .map((t) => (
              <TaskCard key={t.id} task={t} />
            ))}
        </div>
      )}
    </section>
  )
}

export function TaskBoard() {
  const tasks = useHub((s) => s.tasks)
  const everything = Object.values(tasks)
  const all = everything.filter((t) => !t.archived_at)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <RecurringPanel />
      <ArchivedPanel tasks={everything.filter((t) => t.archived_at)} />
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto md:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        const rows = all
          .filter((t) => col.statuses.includes(t.status))
          .sort((a, b) =>
            col.id === 'queued'
              ? (a.scheduled_for ?? a.created_at).localeCompare(b.scheduled_for ?? b.created_at)
              : b.updated_at.localeCompare(a.updated_at),
          )
        return (
          <section key={col.id} className="flex min-h-0 flex-col rounded-3xl bg-surface-container p-3">
            <header className="mb-3 flex items-center justify-between px-1">
              <h2 className="text-sm font-semibold">{col.label}</h2>
              <span className="rounded-full bg-surface-container-highest px-2 text-xs tabular-nums text-on-surface-variant">{rows.length}</span>
            </header>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
              {rows.map((t) => (
                <TaskCard key={t.id} task={t} />
              ))}
              {!rows.length && <p className="px-1 py-6 text-center text-xs text-on-surface-variant">Nothing here</p>}
            </div>
          </section>
        )
      })}
    </div>
    </div>
  )
}
