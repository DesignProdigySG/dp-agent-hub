import { useEffect, useState, type ChangeEvent, type ReactNode } from 'react'

import { fieldClass } from '../../components/Dialog'
import { Button, Icon, relativeTime } from '../../components/ui'
import { api, type KnowledgeDoc, type SearchHit, type Skill } from '../../lib/api'
import { useHub } from '../../store/hub'
import { Card, ConfirmDelete, Field, Notice, type Library } from './common'
import { MarkdownEditor } from '../../components/MarkdownEditor'

function usedBy(key: 'skills' | 'knowledge', name: string) {
  return useHub.getState().agents.filter((a) => a[key].includes(name)).map((a) => a.name)
}

function ListPane<T extends { id: string }>({ items, selected, onSelect, onNew, newLabel, render, empty }: { items: T[]; selected: string | null; onSelect: (id: string) => void; onNew: () => void; newLabel: string; render: (t: T) => ReactNode; empty: string }) {
  return (
    <aside className="flex w-64 shrink-0 flex-col gap-2 overflow-y-auto rounded-3xl bg-surface-container p-3">
      <Button variant="tonal" onClick={onNew} className="w-full">
        <Icon name="add" /> {newLabel}
      </Button>
      {items.map((it) => (
        <button key={it.id} onClick={() => onSelect(it.id)} className={`rounded-2xl px-3 py-2 text-left ${selected === it.id ? 'bg-secondary-container text-on-secondary-container' : 'hover:bg-on-surface/5'}`}>
          {render(it)}
        </button>
      ))}
      {!items.length && <p className="px-2 py-4 text-center text-sm text-on-surface-variant">{empty}</p>}
    </aside>
  )
}

// --- Skills -----------------------------------------------------------------------------------

const BLANK_SKILL = { name: '', description: '', body: '' }

export function SkillsPanel({ library }: { library: Library }) {
  const [selected, setSelected] = useState<string | null>(library.skills[0]?.id ?? null)
  const [draft, setDraft] = useState(BLANK_SKILL)
  const [error, setError] = useState('')
  const current = library.skills.find((s) => s.id === selected)

  useEffect(() => {
    setDraft(current ? { name: current.name, description: current.description, body: current.body } : BLANK_SKILL)
    setError('')
  }, [current])

  const save = async () => {
    try {
      const saved: Skill = current ? await api.updateSkill(current.id, draft) : await api.createSkill(draft)
      library.reload()
      setSelected(saved.id)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const remove = async () => {
    if (!current) return
    await api.deleteSkill(current.id).catch((e: Error) => setError(e.message))
    setSelected(null)
    library.reload()
  }
  const users = current ? usedBy('skills', current.name) : []
  const dirty = current ? draft.name !== current.name || draft.description !== current.description || draft.body !== current.body : draft.name.trim() !== ''

  return (
    <div className="flex h-full min-h-0 gap-3">
      <ListPane
        items={library.skills}
        selected={selected}
        onSelect={setSelected}
        onNew={() => setSelected(null)}
        newLabel="New skill"
        empty="No skills yet."
        render={(s) => (
          <>
            <span className="block truncate text-sm font-medium">{s.name}</span>
            <span className="block truncate text-xs opacity-75">{s.description || 'No description'}</span>
          </>
        )}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Card
          title={current ? current.name : 'New skill'}
          icon="school"
          description="A reusable playbook: steps, rules and examples for one kind of job. Agents see the name and description and load the body on demand."
        >
          <div className="space-y-4">
            <Field label="Name">
              <input className={fieldClass} maxLength={80} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Webinar launch checklist" />
            </Field>
            <Field label="When to use it" help="One line. The agent reads this to decide whether to load the skill.">
              <input className={fieldClass} maxLength={500} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="e.g. Use when cloning and launching a webinar program" />
            </Field>
            <Field label="Instructions (Markdown)">
              <MarkdownEditor label="Skill" minHeight="min-h-72" value={draft.body} onChange={(body) => setDraft({ ...draft, body })} placeholder={'1. Clone the program from the template...\n2. Update the {{my.Event Date}} token...'} />
            </Field>
            {users.length > 0 && <Notice>Used by {users.join(', ')}.</Notice>}
            {error && <Notice tone="error">{error}</Notice>}
            <div className="flex items-center gap-2">
              {current && <ConfirmDelete onConfirm={remove} />}
              <span className="flex-1" />
              <Button disabled={!dirty || !draft.name.trim()} onClick={save}>
                <Icon name="save" /> {current ? 'Save skill' : 'Create skill'}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

// --- Knowledge --------------------------------------------------------------------------------

const BLANK_DOC = { title: '', source: '', content: '' }
const MAX_FILE_BYTES = 2_000_000

function indexLabel(d: KnowledgeDoc) {
  if (d.index_error) return 'Keyword only: embedding failed'
  if (!d.indexed_at) return 'Not indexed'
  return `${d.chunks ?? '?'} chunks · ${d.embedding_model ? `embedded with ${d.embedding_model}` : 'keyword search'}`
}

function SearchBox() {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<{ mode: string; results: SearchHit[] } | null>(null)
  const [error, setError] = useState('')
  const run = () =>
    q.trim() &&
    api
      .searchKnowledge(q.trim())
      .then(setRes)
      .catch((e: Error) => setError(e.message))
  return (
    <Card title="Try a search" icon="search" description="What an agent's search_knowledge tool would return, across all documents.">
      <div className="flex gap-2">
        <input aria-label="Search query" className={fieldClass} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} placeholder="e.g. where do EMEA leads route?" />
        <Button variant="tonal" onClick={run} disabled={!q.trim()}>
          Search
        </Button>
      </div>
      {error && (
        <div className="mt-2">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {res && (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-on-surface-variant">
            {res.results.length} result{res.results.length === 1 ? '' : 's'} · {res.mode} search
          </p>
          {res.results.map((h, i) => (
            <div key={i} className="rounded-2xl bg-surface p-3 text-sm">
              <div className="mb-1 flex justify-between text-xs text-on-surface-variant">
                <span className="font-medium">{h.title}</span>
                <span className="tabular-nums">{h.score.toFixed(3)}</span>
              </div>
              <p className="line-clamp-4 whitespace-pre-wrap">{h.content}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export function KnowledgePanel({ library }: { library: Library }) {
  const [selected, setSelected] = useState<string | null>(library.docs[0]?.id ?? null)
  const [draft, setDraft] = useState(BLANK_DOC)
  const [loadedFor, setLoadedFor] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const current = library.docs.find((d) => d.id === selected)

  useEffect(() => {
    setError('')
    setNote('')
    if (!selected) {
      setDraft(BLANK_DOC)
      setLoadedFor(null)
      return
    }
    api
      .knowledgeDoc(selected)
      .then((d) => {
        setDraft({ title: d.title, source: d.source, content: d.content ?? '' })
        setLoadedFor(selected)
      })
      .catch((e: Error) => setError(e.message))
  }, [selected])

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > MAX_FILE_BYTES) {
      setError('Files up to 2 MB of text are supported')
      return
    }
    file.text().then((content) => setDraft((d) => ({ title: d.title || file.name.replace(/\.[^.]+$/, ''), source: file.name, content })))
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const saved = current ? await api.updateDoc(current.id, draft) : await api.createDoc(draft)
      library.reload()
      setSelected(saved.id)
      setNote(saved.index_error ? `Saved. Embedding failed, so keyword search is used: ${saved.index_error}` : 'Saved and indexed.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const remove = async () => {
    if (!current) return
    await api.deleteDoc(current.id).catch((e: Error) => setError(e.message))
    setSelected(null)
    library.reload()
  }
  const reindex = async () => {
    setNote('Re-indexing...')
    const r = await api.reindex().catch((e: Error) => (setError(e.message), null))
    if (r) setNote(`Re-indexed ${r.reindexed} document${r.reindexed === 1 ? '' : 's'}.`)
    library.reload()
  }
  const users = current ? usedBy('knowledge', current.title) : []
  const ready = !selected || loadedFor === selected

  return (
    <div className="flex h-full min-h-0 gap-3">
      <ListPane
        items={library.docs}
        selected={selected}
        onSelect={setSelected}
        onNew={() => setSelected(null)}
        newLabel="New document"
        empty="No documents yet."
        render={(d) => (
          <>
            <span className="block truncate text-sm font-medium">{d.title}</span>
            <span className={`block truncate text-xs ${d.index_error ? 'text-error' : 'opacity-75'}`}>{indexLabel(d)}</span>
          </>
        )}
      />
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
        <Card
          title={current ? current.title : 'New document'}
          icon="menu_book"
          description={
            <>
              Policies, ICP definitions, routing rules, brand guides. Split into passages and indexed for search.{' '}
              {library.vectorSearch ? 'Vector search runs in Postgres (pgvector).' : 'Set an embedding model in Settings › Knowledge search for semantic search.'}
            </>
          }
          actions={
            <Button variant="text" onClick={reindex} title="Re-embed every document with the current model">
              <Icon name="refresh" /> Re-index all
            </Button>
          }
        >
          {ready ? (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
                <Field label="Title">
                  <input className={fieldClass} maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="e.g. Routing matrix FY27" />
                </Field>
                <Field label="Import text">
                  <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full bg-secondary-container px-4 text-sm font-medium text-on-secondary-container">
                    <Icon name="upload_file" /> Upload .md / .txt
                    <input type="file" accept=".md,.markdown,.txt,.csv,.json,.html,text/*" className="sr-only" onChange={onFile} />
                  </label>
                </Field>
              </div>
              <Field label="Content" help={`${draft.content.length.toLocaleString()} characters${draft.source ? ` · from ${draft.source}` : ''}`}>
                <MarkdownEditor label="Document" minHeight="min-h-72" value={draft.content} onChange={(content) => setDraft({ ...draft, content })} placeholder="Paste text, or upload a file." />
              </Field>
              {current && <p className="text-xs text-on-surface-variant">{indexLabel(current)}{current.indexed_at ? ` · ${relativeTime(current.indexed_at)}` : ''}</p>}
              {users.length > 0 && <Notice>Used by {users.join(', ')}.</Notice>}
              {note && <Notice>{note}</Notice>}
              {error && <Notice tone="error">{error}</Notice>}
              <div className="flex items-center gap-2">
                {current && <ConfirmDelete onConfirm={remove} />}
                <span className="flex-1" />
                <Button disabled={saving || !draft.title.trim() || !draft.content.trim()} onClick={save}>
                  <Icon name="save" /> {saving ? 'Indexing...' : current ? 'Save document' : 'Add document'}
                </Button>
              </div>
            </div>
          ) : (
            <div className="h-64 rounded-2xl bg-surface" />
          )}
        </Card>
        {library.docs.length > 0 && <SearchBox />}
      </div>
    </div>
  )
}
