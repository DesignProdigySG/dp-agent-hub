import { useEffect, useState } from 'react'

import { api, type Risk } from '../lib/api'
import { useHub } from '../store/hub'
import { RiskChip } from '../views/agents/common'
import { Dialog, fieldClass } from './Dialog'
import { Button, Icon, metricLabel } from './ui'
import { Markdown } from './Markdown'

const fmt = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 6)
  return (
    <div className="overflow-x-auto rounded-xl border border-outline-variant">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-container-highest">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1.5 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-outline-variant">
              {cols.map((c) => (
                <td key={c} className="max-w-[220px] truncate px-2 py-1" title={fmt(r[c])}>
                  {fmt(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HtmlPreview({ html }: { html: string }) {
  const [source, setSource] = useState(false)
  return (
    <div className="space-y-2">
      {/* sandboxed: no scripts, no same-origin access */}
      <iframe title="Snippet preview" sandbox="" srcDoc={html} className="h-56 w-full rounded-xl border border-outline-variant bg-white" />
      <button className="text-xs text-primary" onClick={() => setSource(!source)}>
        {source ? 'Hide' : 'Show'} HTML source
      </button>
      {source && <pre className="max-h-48 overflow-auto rounded-xl bg-surface p-2 text-[11px]">{html}</pre>}
    </div>
  )
}

/** Render an approval's details generically: tables for row lists, previews for HTML. */
function Details({ details }: { details: Record<string, unknown> }) {
  return (
    <div className="space-y-4">
      {Object.entries(details).map(([k, v]) => (
        <div key={k}>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">{metricLabel(k)}</div>
          {k === 'html' && typeof v === 'string' ? (
            <HtmlPreview html={v} />
          ) : Array.isArray(v) && v.length && typeof v[0] === 'object' ? (
            <Table rows={v as Record<string, unknown>[]} />
          ) : v && typeof v === 'object' && !Array.isArray(v) ? (
            <Table rows={[v as Record<string, unknown>]} />
          ) : (
            <div className="text-sm">{fmt(v)}</div>
          )}
        </div>
      ))}
    </div>
  )
}

interface ToolCall {
  tool: string
  risk: Risk
  args: Record<string, unknown>
}

const toolCalls = (details: Record<string, unknown>): ToolCall[] | null =>
  Array.isArray(details.calls) && details.calls.every((c) => c && typeof c === 'object' && 'tool' in c) ? (details.calls as ToolCall[]) : null

const editsChanged = (current: string[], original: string[]) => current.some((t, i) => t !== original[i])

interface ReviewItem {
  verb: string
  kind: string
  label: string
  id: string | null
  name: string
  subject: string
  url: string | null
  design_id: string | null
  /** a fix round: each step, for its agent */
  steps?: { agent: string; title: string; brief: string }[]
}

const reviewItems = (details: Record<string, unknown>): ReviewItem[] => (Array.isArray(details.items) ? (details.items as ReviewItem[]) : [])

/** The agent's own design, as it'll look (sandboxed: no scripts, no navigation). */
function DesignPreview({ id }: { id: string }) {
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.design(id).then((d) => setHtml(d.html)).catch((e: Error) => setError(e.message))
  }, [id])
  if (error) return <p className="text-xs text-error">{error}</p>
  if (html === null) return <p className="text-xs text-on-surface-variant">Loading preview…</p>
  return <iframe title="Design preview" sandbox="" srcDoc={html} className="h-[420px] w-full rounded-xl border border-outline-variant bg-white" />
}

/** What the approval is about: each item named, with its Marketo link and a preview.
 * With `ticked`, each item has a tick box: approve some, send the rest back. */
function ReviewItems({ items, ticked, onTick }: { items: ReviewItem[]; ticked?: Set<number>; onTick?: (i: number) => void }) {
  const [open, setOpen] = useState<number | null>(items.findIndex((i) => i.design_id) >= 0 ? items.findIndex((i) => i.design_id) : null)
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
        What you’re approving{ticked && items.length > 1 ? ' · untick anything you want changed or left out' : ''}
      </div>
      {items.map((it, i) => (
        <div key={i} className={`rounded-2xl border p-3 ${ticked && !ticked.has(i) ? 'border-dashed border-outline-variant opacity-70' : 'border-outline-variant'}`}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {ticked && onTick && (
              <input type="checkbox" aria-label={`Approve ${it.name || it.label}`} className="h-4 w-4 accent-[var(--color-primary)]" checked={ticked.has(i)} onChange={() => onTick(i)} />
            )}
            <span className="rounded-full bg-primary-container px-2 py-0.5 text-xs font-medium text-on-primary-container">{it.verb}</span>
            <span className="text-on-surface-variant">{it.label}</span>
            <span className="font-medium">{it.name || (it.id ? `#${it.id}` : '')}</span>
            <span className="flex-1" />
            {it.design_id && (
              <Button variant="text" className="!h-8 !px-2" onClick={() => setOpen(open === i ? null : i)}>
                <Icon name="visibility" /> {open === i ? 'Hide' : 'Preview'}
              </Button>
            )}
            {it.url && (
              <a href={it.url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1 rounded-full px-2 text-sm font-medium text-primary hover:bg-primary/10">
                <Icon name="open_in_new" className="!text-[18px]" /> Open in Marketo
              </a>
            )}
          </div>
          {it.subject && <p className="mt-1 text-xs text-on-surface-variant">Subject: {it.subject}</p>}
          {it.steps && (
            <ol className="mt-2 space-y-2">
              {it.steps.map((st, j) => (
                <li key={j} className="rounded-xl bg-surface p-2 text-sm">
                  <span className="font-medium">
                    {j + 1}. {st.agent}: {st.title}
                  </span>
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-primary">Brief</summary>
                    <Markdown text={st.brief} className="mt-1 text-xs text-on-surface-variant" />
                  </details>
                </li>
              ))}
            </ol>
          )}
          {open === i && it.design_id && (
            <div className="mt-2">
              <DesignPreview id={it.design_id} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/** A custom agent's paused tool calls, with editable arguments (JSON). */
function CallEditor({ calls, drafts, onChange }: { calls: ToolCall[]; drafts: string[]; onChange: (i: number, text: string) => void }) {
  return (
    <div className="space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant">Tool calls · edit arguments before approving if needed</div>
      {calls.map((c, i) => (
        <div key={i} className="rounded-2xl border border-outline-variant p-3">
          <div className="mb-2 flex items-center gap-2 text-sm">
            <code className="font-medium">{c.tool}</code>
            <RiskChip risk={c.risk} />
          </div>
          <textarea
            aria-label={`Arguments for ${c.tool}`}
            rows={Math.min(12, drafts[i].split('\n').length + 1)}
            spellCheck={false}
            className={`${fieldClass} font-mono text-xs`}
            value={drafts[i]}
            onChange={(e) => onChange(i, e.target.value)}
          />
        </div>
      ))}
    </div>
  )
}

interface WorkflowDecisionCard {
  summary?: string
  facts?: Record<string, unknown>
  lead?: { firstName?: string; lastName?: string; title?: string; company?: string }
}

/** A code-defined workflow's decision card: who it's about, the workflow's facts, a summary. */
function WorkflowCard({ details }: { details: Record<string, unknown> }) {
  const card = (details.card ?? {}) as WorkflowDecisionCard
  const lead = card.lead ?? {}
  const facts: [string, unknown][] = [
    ['Lead', [[lead.firstName, lead.lastName].filter(Boolean).join(' '), lead.title, lead.company].filter(Boolean).join(' · ')],
    ...Object.entries(card.facts ?? {}),
  ]
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {facts
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-on-surface-variant">{k}</dt>
              <dd className="min-w-0 break-words">{fmt(v)}</dd>
            </div>
          ))}
      </dl>
      {card.summary && <p className="text-sm">{card.summary}</p>}
    </div>
  )
}

interface Pick {
  id: number
  label: string
  detail?: string
}

/** A workflow's proposal, one tick box per item (e.g. each person to take off a list). */
function PickList({ picks, ticked, onTick }: { picks: Pick[]; ticked: Set<number>; onTick: (id: number) => void }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
        {ticked.size} of {picks.length} ticked · untick anyone to leave them out
      </div>
      <ul className="divide-y divide-outline-variant rounded-2xl border border-outline-variant">
        {picks.map((p) => (
          <li key={p.id}>
            <label className={`flex cursor-pointer items-start gap-3 px-3 py-2 text-sm ${ticked.has(p.id) ? '' : 'opacity-60'}`}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-primary)]" checked={ticked.has(p.id)} onChange={() => onTick(p.id)} />
              <span className="min-w-0">
                <span className="font-medium">{p.label}</span>
                {p.detail && <span className="block text-xs text-on-surface-variant">{p.detail}</span>}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

const toggle = <T,>(set: Set<T>, v: T) => {
  const next = new Set(set)
  if (next.has(v)) next.delete(v)
  else next.add(v)
  return next
}

export function ApprovalModal() {
  const id = useHub((s) => s.reviewApprovalId)
  const approval = useHub((s) => (id ? s.approvals[id] : undefined))
  const agent = useHub((s) => s.agents.find((a) => a.id === approval?.agent_id))
  const task = useHub((s) => (approval ? s.tasks[approval.task_id] : undefined))
  const close = () => useHub.getState().review(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const calls = approval ? toolCalls(approval.details) : null
  const original = calls?.map((c) => JSON.stringify(c.args, null, 2)) ?? []
  const [drafts, setDrafts] = useState<Record<string, string[]>>({})
  const current = (approval && drafts[approval.id]) || original
  const items = approval ? reviewItems(approval.details) : []
  const picks = (approval?.details.pick as Pick[] | undefined) ?? []
  // ticked items, per approval: everything starts ticked
  const [unticked, setUnticked] = useState<Record<string, Set<number>>>({})
  const off = (approval && unticked[approval.id]) || new Set<number>()

  if (!approval) return null
  const tickable = !!calls && items.length === calls.length && calls.length > 1
  const ticked = new Set((tickable ? calls.map((_, i) => i) : picks.map((p) => p.id)).filter((i) => !off.has(i)))
  const tick = (i: number) => setUnticked({ ...unticked, [approval.id]: toggle(off, i) })

  /** Changed arguments by call position; throws on invalid JSON. */
  const edits = (): Record<number, Record<string, unknown>> | undefined => {
    const out: Record<number, Record<string, unknown>> = {}
    current.forEach((text, i) => {
      if (text === original[i]) return
      let parsed: unknown
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Error(`Arguments for ${calls![i].tool} are not valid JSON`)
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`Arguments for ${calls![i].tool} must be a JSON object`)
      out[i] = parsed as Record<string, unknown>
    })
    return Object.keys(out).length ? out : undefined
  }

  const choices = (approval.details.choices as string[] | undefined) ?? null
  const labels = (approval.details.choice_labels as Record<string, string> | undefined) ?? {}

  const reply = approval.details.kind === 'reply'

  const decide = async (approved: boolean, choice?: string) => {
    setBusy(true)
    setError(null)
    try {
      const some = (tickable && approved && !choice) || (picks.length > 0 && choice === 'approve')
      await api.decide(approval.id, approved, comment, approved && !choice ? edits() : undefined, choice, some ? [...ticked] : undefined)
      setComment('')
      close()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const pending = approval.status === 'pending'
  return (
    <Dialog
      wide
      onClose={close}
      title={
        <span className="flex items-center gap-2">
          <Icon name={reply ? 'forum' : 'front_hand'} filled className={reply ? 'text-primary' : 'text-error'} />
          {agent?.name ?? approval.agent_id} {reply ? 'wants your reply' : 'needs approval'}
        </span>
      }
    >
      <div className="space-y-5">
        <div className="rounded-2xl bg-surface p-4">
          <div className="mb-1 flex items-center gap-2 text-xs text-on-surface-variant">
            <code className="rounded bg-surface-container-highest px-1.5 py-0.5">{approval.action}</code>
            {task && <span>· {task.title}</span>}
          </div>
          {reply ? <Markdown text={approval.summary} className="text-sm" /> : <p className="text-sm font-medium">{approval.summary}</p>}
        </div>
        {reply ? null : choices ? (
          picks.length > 0 && pending ? (
            <PickList picks={picks} ticked={ticked} onTick={tick} />
          ) : approval.details.card ? (
            <WorkflowCard details={approval.details} />
          ) : null
        ) : pending && calls ? (
          <>
            {items.length > 0 && <ReviewItems items={items} ticked={tickable ? ticked : undefined} onTick={tick} />}
            <details className="rounded-2xl bg-surface p-3" open={!items.length}>
              <summary className="cursor-pointer text-sm font-medium">Technical details: the exact Marketo calls</summary>
              <div className="mt-3">
                <CallEditor calls={calls} drafts={current} onChange={(i, text) => setDrafts({ ...drafts, [approval.id]: current.map((d, j) => (j === i ? text : d)) })} />
              </div>
            </details>
          </>
        ) : (
          <Details details={approval.details} />
        )}
        {pending ? (
          <>
            <textarea
              rows={reply ? 3 : 2}
              className={fieldClass}
              placeholder={
                reply
                  ? `Your reply to ${agent?.name ?? 'the agent'}: answer its question or say what to change. It works on it and comes back to you.`
                  : choices
                    ? 'Optional comment (saved to the audit log)'
                    : 'Notes for the agent: what to change, or a question. It revises and comes back to you.'
              }
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            {error && <p className="text-sm text-error">{error}</p>}
            {reply ? (
              <div className="flex flex-wrap justify-end gap-2">
                <Button variant="tonal" disabled={busy} onClick={() => decide(true, 'done')} title="Accept the work as it is and close the task">
                  <Icon name="task_alt" /> Looks good, mark done
                </Button>
                <Button disabled={busy || !comment.trim()} onClick={() => decide(false, 'reply')} title={comment.trim() ? 'Send your reply: the agent continues and comes back to you' : 'Write your reply first'}>
                  <Icon name="send" /> Send reply
                </Button>
              </div>
            ) : choices ? (
              <div className="flex flex-wrap justify-end gap-2">
                {[...choices].reverse().map((c) => (
                  <Button
                    key={c}
                    variant={c === 'approve' ? 'filled' : 'tonal'}
                    disabled={busy || (c === 'approve' && picks.length > 0 && !ticked.size)}
                    onClick={() => decide(c !== 'reject', c)}
                  >
                    <Icon name={c === 'approve' ? 'check' : c === 'reject' ? 'block' : 'trending_down'} /> {labels[c] ?? c}
                    {c === 'approve' && picks.length > 0 && ticked.size < picks.length ? ` (${ticked.size} of ${picks.length})` : ''}
                  </Button>
                ))}
              </div>
            ) : (
              <div className="flex flex-wrap justify-end gap-2">
                <Button variant="text" disabled={busy} onClick={() => decide(false)} title="Stop: nothing is approved and the agent ends the task">
                  <Icon name="block" /> Stop
                </Button>
                <Button
                  variant="tonal"
                  disabled={busy || !comment.trim()}
                  onClick={() => decide(false, 'revise')}
                  title={comment.trim() ? 'Nothing approved yet: the agent works on your notes and comes back to you' : 'Write your notes for the agent first'}
                >
                  <Icon name="edit_note" /> Send back with notes
                </Button>
                <Button disabled={busy || (tickable && !ticked.size)} onClick={() => decide(true)}>
                  <Icon name="check" />{' '}
                  {tickable && ticked.size < calls!.length
                    ? `Approve ${ticked.size}, ${comment.trim() ? 'send back' : 'skip'} ${calls!.length - ticked.size}`
                    : calls && editsChanged(current, original)
                      ? 'Approve edited & resume'
                      : tickable
                        ? 'Approve all'
                        : 'Approve & resume'}
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-on-surface-variant">
            This request was {approval.status}
            {approval.details.choice ? ` (${labels[approval.details.choice as string] ?? String(approval.details.choice)})` : ''}
            {approval.comment ? ` — “${approval.comment}”` : ''}.
          </p>
        )}
      </div>
    </Dialog>
  )
}
