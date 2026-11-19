import { useEffect, useRef, useState, type DragEvent } from 'react'

import { api, ATTACHMENT_TYPES, uploadAttachment, type Attachment } from '../lib/api'
import { Button, Icon } from './ui'

const size = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

/** Pick or drop files; each uploads right away, and the parent sends their ids with the
 *  task, schedule or feedback (so a task never starts before its files are there). */
export function AttachmentPicker({ value, onChange, hint }: { value: Attachment[]; onChange: (files: Attachment[]) => void; hint?: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(0)
  const [errors, setErrors] = useState<string[]>([])
  const [over, setOver] = useState(false)
  const latest = useRef(value)
  latest.current = value

  const add = async (files: FileList | File[]) => {
    setErrors([])
    for (const f of Array.from(files)) {
      setBusy((n) => n + 1)
      try {
        const a = await uploadAttachment(f)
        onChange([...latest.current, a])
      } catch (e) {
        setErrors((x) => [...x, (e as Error).message])
      } finally {
        setBusy((n) => n - 1)
      }
    }
  }
  const remove = (a: Attachment) => {
    onChange(value.filter((x) => x.id !== a.id))
    api.deleteAttachment(a.id).catch(() => {}) // unlinked uploads also expire on their own
  }
  const drop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) add(e.dataTransfer.files)
  }

  return (
    <div>
      <div
        onDragOver={(e) => (e.preventDefault(), setOver(true))}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={`flex flex-wrap items-center gap-2 rounded-xl border border-dashed px-3 py-2 text-sm ${over ? 'border-primary bg-primary/5' : 'border-outline-variant'}`}
      >
        {value.map((a) => (
          <span key={a.id} className="flex items-center gap-1 rounded-full bg-secondary-container px-2.5 py-1 text-xs text-on-secondary-container">
            <Icon name="attach_file" className="!text-[14px]" /> {a.filename}
            <span className="opacity-70">{size(a.size)}</span>
            <button type="button" onClick={() => remove(a)} aria-label={`Remove ${a.filename}`} className="ml-0.5 rounded-full hover:bg-on-secondary-container/10">
              <Icon name="close" className="!text-[14px]" />
            </button>
          </span>
        ))}
        <Button type="button" variant="text" className="!h-8 !px-2" onClick={() => input.current?.click()} disabled={busy > 0}>
          <Icon name={busy ? 'hourglass_top' : 'attach_file'} /> {busy ? 'Uploading…' : value.length ? 'Add file' : 'Attach files'}
        </Button>
        {!value.length && !busy && <span className="text-xs text-on-surface-variant">or drop them here</span>}
        <input
          ref={input}
          type="file"
          multiple
          accept={ATTACHMENT_TYPES}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) add(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
      <p className="mt-1 text-xs text-on-surface-variant">{hint ?? 'Markdown, text, CSV, PDF or Word. For this task only: not added to the agent’s knowledge.'}</p>
      {errors.map((m) => (
        <p key={m} className="mt-1 text-xs text-error">
          {m}
        </p>
      ))}
    </div>
  )
}

/** A task's attachments, with the text the agent read and "Keep as knowledge". */
export function AttachmentList({ taskId, canEdit }: { taskId: string; canEdit: boolean }) {
  const [files, setFiles] = useState<Attachment[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [kept, setKept] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  useEffect(() => {
    api.taskAttachments(taskId).then(setFiles).catch(() => setFiles([]))
  }, [taskId])
  useEffect(() => {
    if (!open) return
    setText('')
    api.readAttachment(open).then((a) => setText(a.text + (a.truncated ? '\n\n… (truncated)' : ''))).catch((e: Error) => setText(e.message))
  }, [open])
  if (!files.length) return null
  const keep = async (a: Attachment) => {
    setError('')
    try {
      const doc = await api.keepAttachment(a.id)
      setKept((k) => ({ ...k, [a.id]: doc.title }))
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <section className="rounded-2xl bg-surface-container p-3">
      <h3 className="mb-1.5 flex items-center gap-1 text-sm font-semibold">
        <Icon name="attach_file" className="!text-[18px]" /> Attachments
      </h3>
      <ul className="space-y-1">
        {files.map((a) => (
          <li key={a.id} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <button className="flex items-center gap-1 hover:underline" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <Icon name={open === a.id ? 'expand_less' : 'expand_more'} className="!text-[16px]" /> {a.filename}
              </button>
              <span className="text-xs text-on-surface-variant">
                {size(a.size)} · {a.chars.toLocaleString()} characters{a.round ? ` · with feedback round ${a.round}` : ''}
              </span>
              {canEdit &&
                (kept[a.id] ? (
                  <span className="ml-auto text-xs text-success">Saved as knowledge “{kept[a.id]}”</span>
                ) : (
                  <Button variant="text" className="!ml-auto !h-7 !px-2 text-xs" onClick={() => keep(a)} title="Copy into the knowledge library so any agent can be given it">
                    <Icon name="bookmark_add" className="!text-[16px]" /> Keep as knowledge
                  </Button>
                ))}
            </div>
            {open === a.id && <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-surface p-3 text-xs">{text || 'Loading…'}</pre>}
          </li>
        ))}
      </ul>
      {error && <p className="mt-1 text-xs text-error">{error}</p>}
    </section>
  )
}
