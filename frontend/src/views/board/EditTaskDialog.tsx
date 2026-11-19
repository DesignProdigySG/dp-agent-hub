import { useEffect, useState, type FormEvent } from 'react'

import { AttachmentPicker } from '../../components/Attachments'
import { Dialog, fieldClass } from '../../components/Dialog'
import { Button, Icon, formatWhen } from '../../components/ui'
import { api, type Attachment, type TaskChanges } from '../../lib/api'
import type { TaskOut } from '../../types/contract'
import { plainText } from '../../components/Markdown'
import { MarkdownEditor } from '../../components/MarkdownEditor'

function toLocalInput(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const visibleParams = (p: Record<string, unknown>) => Object.fromEntries(Object.entries(p).filter(([k]) => k !== 'revisions'))

/** Edit a queued task, or a finished one and (optionally) move it back to queued for a fresh
 *  run. Files can only change while the task is queued or as part of moving it back. */
export function EditTaskDialog({ task, onClose }: { task: TaskOut; onClose: () => void }) {
  const finished = task.status === 'done' || task.status === 'failed'
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description)
  const [params, setParams] = useState(JSON.stringify(visibleParams(task.params), null, 2))
  const [asap, setAsap] = useState(!task.scheduled_for || finished)
  const [when, setWhen] = useState(finished ? '' : toLocalInput(task.scheduled_for))
  const [files, setFiles] = useState<Attachment[]>([])
  const [added, setAdded] = useState<Attachment[]>([])
  const [removed, setRemoved] = useState<string[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.taskAttachments(task.id).then(setFiles).catch(() => setFiles([]))
  }, [task.id])

  const changes = (withFiles: boolean): TaskChanges | null => {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(params || '{}')
    } catch {
      setError('Parameters must be valid JSON')
      return null
    }
    return {
      title,
      description,
      params: parsed,
      ...(withFiles || !finished ? { scheduled_for: !asap && when ? new Date(when).toISOString() : null } : {}),
      ...(withFiles ? { attachment_ids: added.map((a) => a.id), remove_attachment_ids: removed } : {}),
    }
  }

  const save = async (requeue: boolean) => {
    setError('')
    const body = changes(requeue || !finished)
    if (!body) return
    setSaving(true)
    try {
      if (requeue) await api.requeueTask(task.id, body)
      else await api.updateTask(task.id, body)
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save(false)
  }

  const kept = files.filter((f) => !removed.includes(f.id))
  return (
    <Dialog title="Edit task" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {finished && (
          <p className="rounded-xl bg-surface-container px-3 py-2 text-xs text-on-surface-variant">
            This task has {task.status === 'done' ? 'finished' : 'failed'}. <b>Save</b> updates its record; <b>Save &amp; move to queued</b> runs it again from a fresh start, with these details. The current result is kept in its history.
          </p>
        )}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Title</label>
          <input required className={fieldClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Description</label>
          <MarkdownEditor label="Description" minHeight="min-h-24" value={description} onChange={setDescription} />
        </div>
        <div className="space-y-2">
          <label className="block text-xs font-medium text-on-surface-variant">{finished ? 'When it runs again' : 'When'}</label>
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
          {!asap && <input type="datetime-local" required className={fieldClass} value={when} onChange={(e) => setWhen(e.target.value)} />}
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Attachments</label>
          {kept.length > 0 && (
            <ul className="mb-2 flex flex-wrap gap-1.5">
              {kept.map((f) => (
                <li key={f.id} className="flex items-center gap-1 rounded-full bg-surface-container-highest px-2.5 py-1 text-xs">
                  <Icon name="attach_file" className="!text-[14px]" /> {f.filename}
                  <button type="button" aria-label={`Remove ${f.filename}`} onClick={() => setRemoved([...removed, f.id])} className="rounded-full hover:bg-on-surface/10">
                    <Icon name="close" className="!text-[14px]" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <AttachmentPicker
            value={added}
            onChange={setAdded}
            hint={finished ? 'File changes apply when you move the task back to queued.' : undefined}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-on-surface-variant">Parameters (JSON)</label>
          <textarea rows={6} spellCheck={false} className={`${fieldClass} font-mono text-xs`} value={params} onChange={(e) => setParams(e.target.value)} />
        </div>
        {task.history.length > 0 && (
          <details className="rounded-xl bg-surface-container px-3 py-2 text-xs">
            <summary className="cursor-pointer font-medium">Earlier runs ({task.history.length})</summary>
            <ol className="mt-2 space-y-2">
              {[...task.history].reverse().map((h) => (
                <li key={String(h.run)}>
                  <div className="text-on-surface-variant">
                    Run {Number(h.run) + 1} · {String(h.status)} · {formatWhen(String(h.at))}
                    {Number(h.feedback_rounds) ? ` · ${h.feedback_rounds} feedback round(s)` : ''}
                  </div>
                  <p className="line-clamp-3 whitespace-pre-line">{plainText(String(h.result || 'No result.'))}</p>
                </li>
              ))}
            </ol>
          </details>
        )}
        {error && <p className="text-sm text-error">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="text" onClick={onClose}>
            Cancel
          </Button>
          {finished && (added.length > 0 || removed.length > 0) ? null : (
            <Button type="submit" variant={finished ? 'tonal' : undefined} disabled={saving}>
              Save
            </Button>
          )}
          {finished && (
            <Button type="button" disabled={saving} onClick={() => save(true)}>
              <Icon name="replay" /> Save &amp; move to queued
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  )
}
