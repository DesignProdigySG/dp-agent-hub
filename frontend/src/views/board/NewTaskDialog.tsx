import { useState, type FormEvent } from 'react'

import { AttachmentPicker } from '../../components/Attachments'
import { Dialog, fieldClass } from '../../components/Dialog'
import { Button } from '../../components/ui'
import { api, type Attachment } from '../../lib/api'
import { useSchedules } from '../../store/schedules'
import { localTz, ONCE, RepeatPicker, type Repeat } from './RepeatPicker'
import { useHub } from '../../store/hub'
import type { AgentProfile } from '../../types/contract'

function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fromTemplate(agent: AgentProfile | undefined) {
  const t = agent?.templates[0]
  return { title: t?.title ?? '', description: t?.description ?? '', params: JSON.stringify(t?.params ?? {}, null, 2) }
}

function NewTaskForm({ initialAgentId, date }: { initialAgentId?: string; date?: Date }) {
  const all = useHub((s) => s.agents)
  const agents = all.filter((a) => a.enabled)
  const close = useHub((s) => s.closeNewTask)
  const [agentId, setAgentId] = useState(initialAgentId ?? agents[0]?.id ?? '')
  const agent = agents.find((a) => a.id === agentId)
  const busy = useHub((st) => !!agentId && st.statuses[agentId] && st.statuses[agentId].state !== 'IDLE')
  const [form, setForm] = useState(() => fromTemplate(agent))
  const [when, setWhen] = useState(date ? toLocalInput(date) : '')
  const [asap, setAsap] = useState(!date)
  const [repeat, setRepeat] = useState<Repeat>(ONCE)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [files, setFiles] = useState<Attachment[]>([])

  const pickAgent = (id: string) => {
    setAgentId(id)
    setForm(fromTemplate(agents.find((a) => a.id === id)))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    let params: Record<string, unknown>
    try {
      params = JSON.parse(form.params || '{}')
    } catch {
      setError('Parameters must be valid JSON')
      return
    }
    setSaving(true)
    try {
      if (repeat.kind !== 'once') {
        await api.createSchedule({
          agent_id: agentId, title: form.title, description: form.description, params,
          kind: repeat.kind, every_minutes: repeat.every_minutes, at_time: repeat.at_time,
          weekdays: repeat.weekdays, tz: localTz(), enabled: true,
          attachment_ids: files.map((f) => f.id),
        })
        await useSchedules.getState().load()
        close()
        return
      }
      await api.createTask({
        agent_id: agentId,
        title: form.title,
        description: form.description,
        params,
        scheduled_for: !asap && when ? new Date(when).toISOString() : null,
        attachment_ids: files.map((f) => f.id),
      })
      close()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  if (!agents.length) {
    return (
      <div className="space-y-4 text-sm text-on-surface-variant">
        <p>{all.length ? 'Every agent is disabled. Enable one to assign it tasks.' : 'There are no agents yet. Create one, then assign it tasks.'}</p>
        <div className="flex justify-end gap-2">
          <Button variant="text" onClick={close}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              close()
              useHub.getState().editAgent(all[0]?.id ?? 'new')
            }}
          >
            {all.length ? 'Open agents' : 'Create an agent'}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Agent</label>
        <div className="grid grid-cols-3 gap-2">
          {agents.map((a) => (
            <button
              type="button"
              key={a.id}
              onClick={() => pickAgent(a.id)}
              className={`rounded-xl border px-2 py-2 text-left text-xs transition ${
                a.id === agentId ? 'border-2 bg-surface' : 'border-outline-variant hover:bg-on-surface/5'
              }`}
              style={a.id === agentId ? { borderColor: a.color } : undefined}
            >
              <div className="font-semibold" style={{ color: a.color }}>
                {a.name}
              </div>
              <div className="truncate text-on-surface-variant">{a.title}</div>
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Title</label>
        <input required className={fieldClass} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Description</label>
        <input className={fieldClass} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Repeat</label>
        <RepeatPicker value={repeat} onChange={setRepeat} />
      </div>
      {repeat.kind === 'once' && (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-on-surface-variant">When</label>
          <div className="flex w-fit rounded-full border border-outline-variant p-0.5" role="group" aria-label="When">
            {[
              [true, 'ASAP'],
              [false, 'At a time'],
            ].map(([v, label]) => (
              <button
                type="button"
                key={String(label)}
                aria-pressed={asap === v}
                onClick={() => setAsap(v as boolean)}
                className={`rounded-full px-3 py-1 text-xs ${asap === v ? 'bg-secondary-container font-medium text-on-secondary-container' : 'text-on-surface-variant hover:bg-on-surface/5'}`}
              >
                {label as string}
              </button>
            ))}
          </div>
          {asap ? (
            <p className="text-xs text-on-surface-variant">
              {agent && busy ? `${agent.name} is busy; this runs as soon as it's free.` : 'Runs at the next available moment.'}
            </p>
          ) : (
            <input type="datetime-local" required className={fieldClass} value={when} onChange={(e) => setWhen(e.target.value)} />
          )}
        </div>
      )}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Attachments</label>
        <AttachmentPicker
          value={files}
          onChange={setFiles}
          hint={
            repeat.kind !== 'once'
              ? 'Copied into every run of this recurring task. Markdown, text, CSV, PDF or Word.'
              : undefined
          }
        />
      </div>
      <div>
        <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Parameters (JSON)</label>
        <textarea
          rows={8}
          spellCheck={false}
          className={`${fieldClass} font-mono text-xs`}
          value={form.params}
          onChange={(e) => setForm({ ...form, params: e.target.value })}
        />
      </div>
      {error && <p className="text-sm text-error">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="text" onClick={close}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving || !agentId}>
          {repeat.kind !== 'once' ? 'Create recurring task' : asap ? 'Run ASAP' : 'Schedule task'}
        </Button>
      </div>
    </form>
  )
}

export function NewTaskDialog() {
  const nt = useHub((s) => s.newTask)
  const close = useHub((s) => s.closeNewTask)
  if (!nt.open) return null
  return (
    <Dialog title="New task" onClose={close}>
      <NewTaskForm initialAgentId={nt.agentId} date={nt.date} />
    </Dialog>
  )
}
