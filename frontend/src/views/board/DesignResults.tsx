import { useEffect, useState } from 'react'

import { AttachmentPicker } from '../../components/Attachments'
import { Button, Icon } from '../../components/ui'
import { api, type Attachment, type DesignGroup, type DesignVersion } from '../../lib/api'

const KIND: Record<DesignVersion['kind'], { label: string; icon: string }> = {
  landing_page: { label: 'Landing page', icon: 'web' },
  form: { label: 'Form', icon: 'list_alt' },
  email: { label: 'Email', icon: 'mail' },
}

function Checks({ v }: { v: DesignVersion }) {
  const { errors, warnings } = v.checks
  if (!errors.length && !warnings.length)
    return (
      <p className="flex items-center gap-1 text-xs text-success">
        <Icon name="verified" className="!text-[16px]" /> Passes the brand check
      </p>
    )
  return (
    <ul className="space-y-0.5 text-xs">
      {errors.map((e) => (
        <li key={e} className="flex gap-1 text-error">
          <Icon name="error" className="!text-[16px]" /> {e}
        </li>
      ))}
      {warnings.map((w) => (
        <li key={w} className="flex gap-1 text-on-surface-variant">
          <Icon name="warning" className="!text-[16px]" /> {w}
        </li>
      ))}
    </ul>
  )
}

/** One deliverable: version picker, brand check, sandboxed live preview, Marketo export. */
function Deliverable({ group }: { group: DesignGroup }) {
  const [id, setId] = useState(group.versions[0].id)
  const [width, setWidth] = useState<'desktop' | 'mobile'>('desktop')
  const [html, setHtml] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const v = group.versions.find((x) => x.id === id) ?? group.versions[0]
  useEffect(() => setId(group.versions[0].id), [group.versions])
  useEffect(() => {
    setHtml('')
    api.design(v.id).then((d) => setHtml(d.html)).catch((e: Error) => setError(e.message))
  }, [v.id])
  const copy = async () => {
    const d = await api.design(v.id, 'export')
    await navigator.clipboard.writeText(d.html)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <select className="rounded-lg border border-outline-variant bg-surface px-2 py-1 text-sm" value={v.id} onChange={(e) => setId(e.target.value)} aria-label="Version">
          {group.versions.map((x) => (
            <option key={x.id} value={x.id}>
              v{x.version} · {x.round ? `feedback round ${x.round}` : 'first draft'} · {new Date(x.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </option>
          ))}
        </select>
        {group.kind !== 'form' && (
          <span className="flex rounded-full bg-surface-container-highest p-0.5 text-xs">
            {(['desktop', 'mobile'] as const).map((w) => (
              <button key={w} onClick={() => setWidth(w)} className={`rounded-full px-2.5 py-1 ${width === w ? 'bg-surface shadow-sm' : 'text-on-surface-variant'}`}>
                <Icon name={w === 'desktop' ? 'desktop_windows' : 'smartphone'} className="!text-[15px]" /> {w === 'desktop' ? 'Desktop' : 'Mobile'}
              </button>
            ))}
          </span>
        )}
        <span className="ml-auto flex gap-1">
          {group.kind !== 'form' && (
            <Button variant="text" className="!h-8 !px-3" onClick={copy} title="HTML ready to paste into Marketo (tokens kept, form embedded once created)">
              <Icon name={copied ? 'check' : 'content_copy'} /> {copied ? 'Copied' : 'Copy for Marketo'}
            </Button>
          )}
        </span>
      </div>
      {group.kind === 'email' && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
          <dt className="text-on-surface-variant">Subject</dt>
          <dd>{v.subject}</dd>
          <dt className="text-on-surface-variant">Preheader</dt>
          <dd className="text-on-surface-variant">{v.preheader}</dd>
        </dl>
      )}
      {group.kind === 'form' && (
        <p className="text-sm">
          {v.marketo.form_id ? (
            <>
              <Icon name="cloud_done" className="!text-[16px] text-success" /> In Marketo as form {v.marketo.form_id}
            </>
          ) : (
            <span className="text-on-surface-variant">Not created in Marketo yet.</span>
          )}
        </p>
      )}
      {group.kind !== 'form' && (
        <p className="text-sm">
          {v.marketo.email_id || v.marketo.landing_page_id ? (
            <>
              <Icon name="cloud_done" className="!text-[16px] text-success" />{' '}
              {group.kind === 'email'
                ? `In Marketo as email ${v.marketo.email_id} (template ${v.marketo.email_template_id})`
                : `In Marketo as landing page ${v.marketo.landing_page_id} (template ${v.marketo.landing_page_template_id})`}
              , draft. Review and approve it in Marketo.
            </>
          ) : (
            <span className="text-on-surface-variant">Not published to Marketo yet.</span>
          )}
        </p>
      )}
      <Checks v={v} />
      {error && <p className="text-sm text-error">{error}</p>}
      <div className="flex justify-center overflow-hidden rounded-2xl border border-outline-variant bg-surface-container-highest p-2">
        {html ? (
          // Scripts may run (Tailwind's CDN), but without same-origin access the page can't
          // reach the hub, its cookies or its API.
          <iframe title={`${group.name} v${v.version}`} sandbox="allow-scripts" srcDoc={html} className="h-[70vh] rounded-lg bg-white transition-[width]" style={{ width: width === 'mobile' || group.kind === 'form' ? 390 : '100%' }} />
        ) : (
          <div className="flex h-40 items-center text-sm text-on-surface-variant">Loading preview…</div>
        )}
      </div>
    </section>
  )
}

/** A Designer task's deliverables. */
export function DesignResults({ groups }: { groups: DesignGroup[] }) {
  const [tab, setTab] = useState(0)
  const group = groups[Math.min(tab, groups.length - 1)]
  return (
    <div className="space-y-3">
      <nav className="flex flex-wrap gap-1">
        {groups.map((g, i) => (
          <button key={`${g.kind}:${g.name}`} onClick={() => setTab(i)} className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-sm ${i === tab ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant hover:bg-surface-container-highest'}`}>
            <Icon name={KIND[g.kind].icon} className="!text-[16px]" /> {g.name}
            <span className="text-xs opacity-70">v{g.versions[0].version}</span>
            {g.versions[0].checks.errors.length > 0 && <Icon name="error" className="!text-[14px] text-error" />}
          </button>
        ))}
      </nav>
      <Deliverable key={`${group.kind}:${group.name}`} group={group} />
    </div>
  )
}

/** Send the agent back to work on the same task with notes. */
export function FeedbackBox({ taskId, onSent }: { taskId: string; onSent: () => void }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<Attachment[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const send = async () => {
    setBusy(true)
    setError('')
    try {
      await api.taskFeedback(taskId, text, files.map((f) => f.id))
      setText('')
      setFiles([])
      onSent()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="space-y-2 rounded-2xl bg-surface-container p-3">
      <label className="block text-sm font-semibold" htmlFor="feedback">
        Request changes
      </label>
      <textarea
        id="feedback"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Use the aerial Avalon photo in the hero, add the ferry option to the details, and make the email shorter."
        className="w-full rounded-xl border border-outline-variant bg-surface px-3 py-2 text-sm"
      />
      <AttachmentPicker value={files} onChange={setFiles} hint="Optional: files for this round, e.g. an updated brief or speaker list." />
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-on-surface-variant">The agent revises the same task; earlier versions stay available.</p>
        <Button onClick={send} disabled={busy || text.trim().length < 3}>
          <Icon name="send" /> {busy ? 'Sending…' : 'Send feedback'}
        </Button>
      </div>
      {error && <p className="text-xs text-error">{error}</p>}
    </section>
  )
}
