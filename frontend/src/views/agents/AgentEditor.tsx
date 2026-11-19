import { useEffect, useMemo, useState } from 'react'

import { fieldClass } from '../../components/Dialog'
import { AgentBadge } from '../../components/AgentBadge'
import { Button, Icon, relativeTime } from '../../components/ui'
import { api, type AgentConfig, type Autonomy, type Memory } from '../../lib/api'
import { CHARACTERS, characterLabel, characterOf, characterPreview } from '../../lib/characters'
import { useHub } from '../../store/hub'
import { ZONE_INFO, ZONES } from '../spatial/layout'
import { Card, ConfirmDelete, Field, Notice, RiskChip, Toggle, type Library } from './common'
import { MarkdownEditor } from '../../components/MarkdownEditor'

export const BLANK: AgentConfig = {
  id: '',
  name: '',
  title: '',
  color: '#5b6abf',
  character: '',
  home_zone: 'break_room',
  model_tier: 'standard',
  enabled: true,
  instructions: '',
  tools: [],
  skill_ids: [],
  knowledge_ids: [],
  memory_enabled: false,
  autonomy: 'approve_writes',
  max_steps: 12,
  templates: [{ title: '', description: '', params: {} }],
}

const EDITABLE: (keyof AgentConfig)[] = ['name', 'title', 'color', 'character', 'home_zone', 'model_tier', 'enabled', 'instructions', 'tools', 'skill_ids', 'knowledge_ids', 'memory_enabled', 'autonomy', 'max_steps', 'templates']

const AUTONOMY: { id: Autonomy; label: string; help: string }[] = [
  { id: 'approve_writes', label: 'Approve every change', help: 'Reads run freely. Any write or destructive Marketo action pauses for your approval.' },
  { id: 'approve_destructive', label: 'Approve destructive only', help: 'Creates and updates run on their own. Merges, deletes, activations and approvals pause.' },
  { id: 'autonomous', label: 'Fully autonomous', help: 'Nothing pauses. Only for well-tested agents with narrow tools.' },
]

const TIERS = [
  { id: 'fast', label: 'Fast', help: 'Cheap and quick' },
  { id: 'standard', label: 'Standard', help: 'Balanced' },
  { id: 'strong', label: 'Strong', help: 'Best reasoning, highest cost' },
] as const

/** Where a tool comes from: the hub itself, Adobe's Marketo MCP server, or Marketo's REST APIs. */
type Channel = 'hub' | 'mcp' | 'rest'
const CHANNELS: { id: Channel | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'hub', label: 'Hub' },
  { id: 'mcp', label: 'Marketo MCP' },
  { id: 'rest', label: 'Marketo REST' },
]
const channelOf = (group: string): Channel =>
  group.startsWith('Marketo MCP') ? 'mcp' : group.startsWith('Marketo Asset API') || group === 'Marketo REST' ? 'rest' : 'hub'
const CHANNEL_ORDER: Channel[] = ['hub', 'mcp', 'rest']

function ToolPicker({ library, selected, onChange }: { library: Library; selected: string[]; onChange: (tools: string[]) => void }) {
  const [filter, setFilter] = useState('')
  const [channel, setChannel] = useState<Channel | 'all'>('all')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const { tools } = library
  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const out = new Map<string, typeof tools>()
    for (const t of tools) {
      if (channel !== 'all' && channelOf(t.group) !== channel) continue
      if (q && !t.name.includes(q) && !t.description.toLowerCase().includes(q)) continue
      out.set(t.group, [...(out.get(t.group) ?? []), t])
    }
    // the hub's own tools, then the MCP server's, then the REST APIs', each by topic
    return [...out.entries()].sort(
      ([a], [b]) => CHANNEL_ORDER.indexOf(channelOf(a)) - CHANNEL_ORDER.indexOf(channelOf(b)) || (channelOf(a) === 'hub' ? 0 : a.localeCompare(b)),
    )
  }, [tools, filter, channel])
  const set = new Set(selected)
  const counts = (c: Channel | 'all') => {
    const inIt = tools.filter((t) => c === 'all' || channelOf(t.group) === c)
    return { total: inIt.length, chosen: inIt.filter((t) => set.has(t.name)).length }
  }
  const toggle = (name: string) => onChange(set.has(name) ? selected.filter((n) => n !== name) : [...selected, name])
  const missing = selected.filter((n) => !tools.some((t) => t.name === n))

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <input aria-label="Filter tools" className={fieldClass} placeholder="Filter tools..." value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span className="shrink-0 text-xs text-on-surface-variant tabular-nums">{selected.length} selected</span>
      </div>
      <div role="tablist" aria-label="Tool source" className="flex flex-wrap gap-1">
        {CHANNELS.map((c) => {
          const n = counts(c.id)
          return (
            <button
              key={c.id}
              type="button"
              role="tab"
              aria-selected={channel === c.id}
              onClick={() => setChannel(c.id)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${channel === c.id ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant hover:bg-on-surface/5'}`}
            >
              {c.label} <span className="tabular-nums opacity-70">{n.chosen ? `${n.chosen}/` : ''}{n.total}</span>
            </button>
          )
        })}
      </div>
      {library.mcpError && <Notice tone="warning">{library.mcpError}. MCP tools already chosen are kept.</Notice>}
      {missing.length > 0 && <Notice tone="warning">Not currently available: {missing.join(', ')}</Notice>}
      <div className="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
        {groups.map(([group, items]) => {
          const chosen = items.filter((t) => set.has(t.name)).length
          const isOpen = open[group] ?? (filter.trim() !== '' || chosen > 0 || groups.length <= 3)
          const reads = items.filter((t) => t.risk === 'read' || t.risk === 'internal').map((t) => t.name)
          return (
            <div key={group} className="rounded-xl border border-outline-variant/60">
              <div className="flex items-center gap-2 px-2 py-1.5">
                <button type="button" className="flex min-w-0 flex-1 items-center gap-1 text-left text-xs font-semibold uppercase tracking-wide text-on-surface-variant" onClick={() => setOpen({ ...open, [group]: !isOpen })}>
                  <Icon name={isOpen ? 'expand_less' : 'expand_more'} className="!text-[16px]" />
                  <span className="truncate">{group}</span>
                  <span className="font-normal normal-case tracking-normal tabular-nums">
                    {chosen}/{items.length}
                  </span>
                </button>
                {reads.length > 0 && (
                  <button type="button" className="shrink-0 rounded-full px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10" title="Select every read-only tool in this group" onClick={() => onChange([...new Set([...selected, ...reads])])}>
                    All read-only
                  </button>
                )}
                {chosen > 0 && (
                  <button type="button" className="shrink-0 rounded-full px-2 py-0.5 text-[11px] text-on-surface-variant hover:bg-on-surface/10" onClick={() => onChange(selected.filter((n) => !items.some((t) => t.name === n)))}>
                    None
                  </button>
                )}
              </div>
              {isOpen && (
                <ul className="space-y-0.5 px-1 pb-1">
                  {items.map((t) => (
                    <li key={t.name}>
                      <label className="flex cursor-pointer items-start gap-2.5 rounded-xl px-2 py-1.5 hover:bg-on-surface/5">
                        <input type="checkbox" className="mt-1 accent-[var(--color-primary)]" checked={set.has(t.name)} onChange={() => toggle(t.name)} />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <code className="text-[13px] font-medium">{t.name}</code>
                            <RiskChip risk={t.risk} />
                          </span>
                          <span className="block text-xs text-on-surface-variant">{t.description}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
        {!groups.length && <p className="text-sm text-on-surface-variant">No tools match.</p>}
      </div>
    </div>
  )
}

function CharacterPicker({ value, color, onChange }: { value: string; color: string; onChange: (c: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Character">
      {CHARACTERS.map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          aria-label={characterLabel(c)}
          title={characterLabel(c)}
          onClick={() => onChange(c)}
          className={`relative h-14 w-14 overflow-hidden rounded-2xl ring-2 transition ${value === c ? 'ring-primary' : 'ring-transparent opacity-70 hover:opacity-100'}`}
          style={{ background: `color-mix(in srgb, ${color} 30%, var(--md-surface-container-high))` }}
        >
          <img src={characterPreview(c)} alt="" draggable={false} className="h-full w-full object-contain" />
        </button>
      ))}
    </div>
  )
}

function CheckList<T extends { id: string }>({ items, selected, onChange, label, sub, empty }: { items: T[]; selected: string[]; onChange: (ids: string[]) => void; label: (t: T) => string; sub: (t: T) => string; empty: string }) {
  if (!items.length) return <p className="text-sm text-on-surface-variant">{empty}</p>
  const set = new Set(selected)
  return (
    <ul className="space-y-0.5">
      {items.map((it) => (
        <li key={it.id}>
          <label className="flex cursor-pointer items-start gap-2.5 rounded-xl px-2 py-1.5 hover:bg-on-surface/5">
            <input
              type="checkbox"
              className="mt-1 accent-[var(--color-primary)]"
              checked={set.has(it.id)}
              onChange={() => onChange(set.has(it.id) ? selected.filter((i) => i !== it.id) : [...selected, it.id])}
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{label(it)}</span>
              <span className="block truncate text-xs text-on-surface-variant">{sub(it)}</span>
            </span>
          </label>
        </li>
      ))}
    </ul>
  )
}

function MemoryPanel({ agentId }: { agentId: string }) {
  const [items, setItems] = useState<Memory[] | null>(null)
  const [editing, setEditing] = useState<{ id: string | null; text: string } | null>(null)
  const [error, setError] = useState('')
  const load = () => api.memories(agentId).then(setItems).catch((e: Error) => setError(e.message))
  useEffect(() => {
    load()
  }, [agentId]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!editing?.text.trim()) return
    try {
      if (editing.id) await api.editMemory(agentId, editing.id, editing.text.trim())
      else await api.addMemory(agentId, editing.text.trim())
      setEditing(null)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-on-surface-variant">{items ? `${items.length} saved` : 'Loading...'}</span>
        <Button variant="text" onClick={() => setEditing({ id: null, text: '' })}>
          <Icon name="add" /> Add memory
        </Button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {editing && (
        <div className="space-y-2 rounded-2xl bg-surface p-3">
          <textarea aria-label="Memory text" autoFocus rows={2} className={fieldClass} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
          <div className="flex justify-end gap-2">
            <Button variant="text" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={!editing.text.trim()}>
              Save memory
            </Button>
          </div>
        </div>
      )}
      <ul className="max-h-72 space-y-1 overflow-y-auto">
        {items?.map((m) => (
          <li key={m.id} className="group flex items-start gap-2 rounded-xl px-2 py-1.5 text-sm hover:bg-on-surface/5">
            <Icon name="bookmark" className="mt-0.5 text-on-surface-variant !text-[18px]" />
            <span className="min-w-0 flex-1">
              {m.text}
              <span className="block text-xs text-on-surface-variant">
                {relativeTime(m.updated_at)}
                {m.task_id ? ` · from task ${m.task_id}` : ' · added by hand'}
              </span>
            </span>
            <button className="rounded-full p-1 text-on-surface-variant opacity-0 hover:bg-on-surface/10 group-hover:opacity-100 focus:opacity-100" aria-label="Edit memory" onClick={() => setEditing({ id: m.id, text: m.text })}>
              <Icon name="edit" className="!text-[18px]" />
            </button>
            <button
              className="rounded-full p-1 text-error opacity-0 hover:bg-error/10 group-hover:opacity-100 focus:opacity-100"
              aria-label="Delete memory"
              onClick={() => api.deleteMemory(agentId, m.id).then(load)}
            >
              <Icon name="delete" className="!text-[18px]" />
            </button>
          </li>
        ))}
        {items?.length === 0 && <li className="px-2 text-sm text-on-surface-variant">Nothing remembered yet. The agent saves facts with its remember tool.</li>}
      </ul>
    </div>
  )
}

export function AgentEditor({ agentId, library, onSaved, onDeleted, gotoTab }: { agentId: string; library: Library; onSaved: (id: string) => void; onDeleted: () => void; gotoTab: (tab: 'skills' | 'knowledge') => void }) {
  const isNew = agentId === 'new'
  const [original, setOriginal] = useState<AgentConfig | null>(isNew ? BLANK : null)
  const [draft, setDraft] = useState<AgentConfig>(BLANK)
  const [paramsText, setParamsText] = useState('{}')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const status = useHub((s) => s.statuses[agentId])

  useEffect(() => {
    setError('')
    const apply = (cfg: AgentConfig) => {
      const withTemplate = cfg.templates.length ? cfg : { ...cfg, templates: [{ title: '', description: '', params: {} }] }
      setOriginal(withTemplate)
      setDraft(withTemplate)
      setParamsText(JSON.stringify(withTemplate.templates[0].params ?? {}, null, 2))
    }
    if (isNew) apply({ ...BLANK, character: CHARACTERS[Math.floor(Math.random() * CHARACTERS.length)] })
    else api.agentConfig(agentId).then(apply).catch((e: Error) => setError(e.message))
  }, [agentId, isNew])

  if (!original) return <div className="h-full rounded-3xl bg-surface-container" />
  const workflow = original.workflow
  const set = <K extends keyof AgentConfig>(k: K, v: AgentConfig[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const template = draft.templates[0]
  const setTemplate = (patch: Partial<typeof template>) => set('templates', [{ ...template, ...patch }, ...draft.templates.slice(1)])
  const dirty = JSON.stringify(draft) !== JSON.stringify(original) || paramsText !== JSON.stringify(original.templates[0]?.params ?? {}, null, 2)
  const busy = status && status.state !== 'IDLE'

  const save = async () => {
    let params: Record<string, unknown>
    try {
      params = JSON.parse(paramsText || '{}')
    } catch {
      setError('Task template parameters must be valid JSON')
      return
    }
    const next: AgentConfig = { ...draft, templates: [{ ...template, params }, ...draft.templates.slice(1)] }
    if (!next.templates[0].title.trim()) next.templates = draft.templates.slice(1)
    setSaving(true)
    setError('')
    try {
      const fields = EDITABLE
      const saved = isNew
        ? await api.createAgent(Object.fromEntries(fields.map((k) => [k, next[k]])))
        : await api.updateAgent(agentId, Object.fromEntries(fields.filter((k) => JSON.stringify(next[k]) !== JSON.stringify(original[k])).map((k) => [k, next[k]])))
      onSaved(saved.id)
      if (!isNew) {
        const withTemplate = saved.templates.length ? saved : { ...saved, templates: [{ title: '', description: '', params: {} }] }
        setOriginal(withTemplate)
        setDraft(withTemplate)
        setParamsText(JSON.stringify(withTemplate.templates[0].params ?? {}, null, 2))
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    try {
      await api.deleteAgent(agentId)
      onDeleted()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pb-3">
        <div className="flex items-center gap-3 px-1">
          <AgentBadge agent={{ ...draft, id: draft.id || 'new' }} size={44} />
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold">{isNew ? 'New agent' : original.name}</h1>
            <p className="text-xs text-on-surface-variant">
              {isNew ? 'A tool-calling LangGraph agent configured below.' : `Agent · id ${original.id}`}
            </p>
          </div>
        </div>

        <Card title="Profile" icon="badge">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name">
              <input className={fieldClass} required maxLength={60} value={draft.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. List Builder" />
            </Field>
            <Field label="Role">
              <input className={fieldClass} maxLength={120} value={draft.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Builds and maintains static lists" />
            </Field>
            <Field label="Home zone" help="Where the agent waits and works in the 3D view.">
              <select className={fieldClass} value={draft.home_zone} onChange={(e) => set('home_zone', e.target.value as AgentConfig['home_zone'])}>
                {ZONES.map((z) => (
                  <option key={z} value={z}>
                    {ZONE_INFO[z].label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Model tier" help="Mapped to a model in Settings › LLM router.">
              <select className={fieldClass} value={draft.model_tier} onChange={(e) => set('model_tier', e.target.value as AgentConfig['model_tier'])}>
                {TIERS.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label} · {t.help}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Color">
              <div className="flex items-center gap-2">
                <input type="color" aria-label="Color picker" className="h-9 w-12 cursor-pointer rounded-lg border border-outline-variant bg-surface" value={draft.color} onChange={(e) => set('color', e.target.value)} />
                <input className={`${fieldClass} font-mono`} value={draft.color} onChange={(e) => set('color', e.target.value)} />
              </div>
            </Field>
            <Field label="Character" help="How the agent looks in the 3D view and its avatar." className="sm:col-span-2">
              <CharacterPicker value={characterOf({ id: draft.id || 'new', character: draft.character })} color={draft.color} onChange={(c) => set('character', c)} />
            </Field>
            <Field label="Enabled" help={workflow ? "The kill switch: when off, runs stop before touching Marketo." : "Disabled agents keep their history but don't pick up tasks."}>
              <Toggle label="Enabled" on={draft.enabled} onChange={(v) => set('enabled', v)} />
            </Field>
          </div>
        </Card>

        {workflow ? (
          <Card title="Workflow" icon="account_tree" description="A code-defined LangGraph StateGraph: fixed steps, guardrails enforced in code, and the model used only where the workflow says.">
            <Notice tone="info">
              This agent runs <code className="font-mono">{workflow}</code>. Its rules live in the knowledge document below (the first one is read fresh on every run), and its run settings in the default task. The Enabled toggle is its kill switch.
            </Notice>
          </Card>
        ) : (
          <>
        <Card title="Instructions" icon="description" description="The system prompt: goals, policies, how to decide, what to report. Guardrails against prompt injection are added automatically.">
          <MarkdownEditor
            label="Instructions"
            value={draft.instructions}
            onChange={(v) => set('instructions', v.slice(0, 20000))}
            placeholder="You maintain static lists for regional sales teams. Before adding leads, check the routing matrix in your knowledge..."
          />
        </Card>

        <Card title="Tools" icon="build" description="What the agent can call. Risk decides what needs approval.">
          <ToolPicker library={library} selected={draft.tools} onChange={(t) => set('tools', t)} />
        </Card>

        <Card title="Approvals" icon="front_hand" description="How much the agent may do without asking.">
          <div className="space-y-2" role="radiogroup" aria-label="Autonomy">
            {AUTONOMY.map((a) => (
              <label key={a.id} className={`flex cursor-pointer items-start gap-3 rounded-2xl px-3 py-2.5 ring-1 ${draft.autonomy === a.id ? 'bg-secondary-container ring-transparent' : 'ring-outline-variant hover:bg-on-surface/5'}`}>
                <input type="radio" name="autonomy" className="mt-1 accent-[var(--color-primary)]" checked={draft.autonomy === a.id} onChange={() => set('autonomy', a.id)} />
                <span>
                  <span className="block text-sm font-medium">{a.label}</span>
                  <span className="block text-xs text-on-surface-variant">{a.help}</span>
                </span>
              </label>
            ))}
          </div>
          {draft.autonomy === 'autonomous' && (
            <div className="mt-3">
              <Notice tone="warning">Text the agent reads from Marketo (lead fields, activity data, asset HTML) could try to steer it. With no approvals, a manipulated agent can change your instance. Keep its tools narrow.</Notice>
            </div>
          )}
          <Field label="Max steps per task" help="Each step is one model turn that calls tools. Caps runaway loops and cost." className="mt-4 max-w-xs">
            <input type="number" min={1} max={50} className={`${fieldClass} tabular-nums`} value={draft.max_steps} onChange={(e) => set('max_steps', Number(e.target.value))} />
          </Field>
        </Card>
          </>
        )}

        <div className="grid gap-3 xl:grid-cols-2">
          {!workflow && (
          <Card
            title="Skills"
            icon="school"
            description="The agent sees each name and description, and loads the full playbook when needed."
            actions={
              <Button variant="text" onClick={() => gotoTab('skills')}>
                Manage
              </Button>
            }
          >
            <CheckList items={library.skills} selected={draft.skill_ids} onChange={(ids) => set('skill_ids', ids)} label={(s) => s.name} sub={(s) => s.description} empty="No skills yet. Create reusable playbooks under Skills." />
          </Card>
          )}
          <Card
            title="Knowledge"
            icon="menu_book"
            description={workflow ? 'The first document is the rules the workflow scores with, read on every run. Edit it under Knowledge.' : 'Searchable with the search_knowledge tool.'}
            actions={
              <Button variant="text" onClick={() => gotoTab('knowledge')}>
                Manage
              </Button>
            }
          >
            <CheckList items={library.docs} selected={draft.knowledge_ids} onChange={(ids) => set('knowledge_ids', ids)} label={(d) => d.title} sub={(d) => `${d.chars.toLocaleString()} chars · ${d.embedding_model ? 'semantic' : 'keyword'} search`} empty="No documents yet. Add policies, ICP definitions or brand guides under Knowledge." />
          </Card>
        </div>

        {!workflow && (
        <Card title="Memory" icon="neurology" description="Long-term memory in the LangGraph store. The agent can remember, recall and forget facts across tasks; recent memories are added to its prompt." actions={<Toggle label="Memory enabled" on={draft.memory_enabled} onChange={(v) => set('memory_enabled', v)} />}>
          {draft.memory_enabled && !isNew ? (
            <MemoryPanel agentId={agentId} />
          ) : (
            <p className="text-sm text-on-surface-variant">{draft.memory_enabled ? 'Save the agent to start collecting memories.' : 'Off. The agent starts every task fresh.'}</p>
          )}
        </Card>
        )}

        <Card title="Default task" icon="task" description={workflow ? 'Pre-fills the New task form. Its parameters are the workflow’s run settings; a task can override them.' : 'Pre-fills the New task form for this agent.'}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Title">
              <input className={fieldClass} value={template.title} onChange={(e) => setTemplate({ title: e.target.value })} placeholder="e.g. Weekly list hygiene" />
            </Field>
            <Field label="Description" help={workflow ? undefined : 'Becomes the brief the agent works from.'}>
              <input className={fieldClass} value={template.description} onChange={(e) => setTemplate({ description: e.target.value })} />
            </Field>
            <Field label="Parameters (JSON)" className="sm:col-span-2">
              <textarea rows={4} className={`${fieldClass} font-mono text-xs`} value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
            </Field>
          </div>
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-3xl bg-surface-container-high px-4 py-3">
        {!isNew && <ConfirmDelete onConfirm={remove} disabled={busy} label="Delete agent" />}
        <span className="min-w-0 flex-1 truncate text-sm text-error">{error}</span>
        {busy && <span className="text-xs text-on-surface-variant">Running: changes apply to its next task</span>}
        <Button variant="text" disabled={(!dirty && !isNew) || saving} onClick={() => (isNew ? onDeleted() : (setDraft(original), setParamsText(JSON.stringify(original.templates[0]?.params ?? {}, null, 2))))}>
          {isNew ? 'Cancel' : 'Discard'}
        </Button>
        <Button disabled={(!dirty && !isNew) || saving || !draft.name.trim()} onClick={save}>
          <Icon name="save" /> {saving ? 'Saving...' : isNew ? 'Create agent' : 'Save changes'}
        </Button>
      </div>
    </div>
  )
}
