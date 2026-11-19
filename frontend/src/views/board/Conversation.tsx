/**
 * The conversation on a task (backend app/messages.py): hand-off briefs and replies between
 * agents, your approvals, change requests and notes, and each agent's closing message.
 */
import { useCallback, useEffect, useState } from 'react'

import { AgentBadge } from '../../components/AgentBadge'
import { fieldClass } from '../../components/Dialog'
import { Button, Icon, formatWhen } from '../../components/ui'
import { api, type TaskMessage } from '../../lib/api'
import { useHub } from '../../store/hub'
import type { TaskOut } from '../../types/contract'
import { Markdown } from '../../components/Markdown'

const KIND: Record<string, string> = {
  handoff: 'handed this over',
  handed_on: 'handed work on',
  your_turn: 'your turn',
  reply: 'picked it up',
  approved: 'approved',
  changes: 'asked for changes',
  rejected: 'rejected',
  feedback: 'feedback',
  note: 'note',
  result: 'result',
}

/** What sending does, by the task's state (backend: post_message in routes/api.py). */
const PROMPT: Partial<Record<TaskOut['status'], string>> = {
  queued: 'A note for the agent: it gets it when it starts',
  needs_approval: 'Reply: the agent works on what you say and comes back to you',
  done: 'Reply to continue: the agent picks it up again and comes back to you',
  failed: 'Reply to continue: the agent picks it up again and comes back to you',
}

export function Conversation({ task }: { task: TaskOut }) {
  const [messages, setMessages] = useState<TaskMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const agents = useHub((s) => s.agents)
  const isAdmin = useHub((s) => s.auth.authenticated)

  const load = useCallback(() => api.taskMessages(task.id).then(setMessages).catch((e: Error) => setError(e.message)), [task.id])
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load, task.updated_at])

  const send = async () => {
    setBusy(true)
    setError('')
    try {
      await api.postMessage(task.id, draft.trim())
      setDraft('')
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!messages.length && !isAdmin) return null
  return (
    <section className="space-y-2 rounded-2xl bg-surface p-4">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Icon name="forum" className="!text-[18px]" /> Conversation
      </h3>
      {!messages.length && <p className="text-xs text-on-surface-variant">Nothing said yet. Hand-offs, approvals and your notes show up here.</p>}
      <ul className="space-y-2">
        {messages.map((m) => {
          const you = m.author_id === 'you'
          const agent = agents.find((a) => a.id === m.author_id)
          return (
            <li key={m.id} className={`flex gap-2 ${you ? 'flex-row-reverse' : ''}`}>
              {agent ? <AgentBadge agent={agent} size={28} /> : <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-on-primary">You</span>}
              <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${you ? 'bg-primary-container text-on-primary-container' : 'bg-surface-container-high'}`}>
                <div className="mb-0.5 flex flex-wrap items-baseline gap-x-1.5 text-[11px] text-on-surface-variant">
                  <span className="font-semibold" style={agent ? { color: agent.color } : undefined}>
                    {m.author_name || m.author_id}
                  </span>
                  <span>{KIND[m.kind] ?? m.kind}</span>
                  <span>· {formatWhen(m.created_at)}</span>
                </div>
                <Markdown text={m.text} />
              </div>
            </li>
          )
        })}
      </ul>
      {isAdmin && (
        <div className="flex items-end gap-2 pt-1">
          <textarea rows={2} className={fieldClass} placeholder={PROMPT[task.status] ?? 'A note on this task'} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <Button disabled={busy || !draft.trim()} onClick={send}>
            <Icon name="send" /> {task.status === 'queued' || task.status === 'in_progress' ? 'Send' : 'Reply'}
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-error">{error}</p>}
    </section>
  )
}
