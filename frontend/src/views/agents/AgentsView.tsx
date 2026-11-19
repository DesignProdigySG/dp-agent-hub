import { useState } from 'react'

import { AgentBadge } from '../../components/AgentBadge'
import { Button, Chip, Icon, StateBadge } from '../../components/ui'
import { useHub } from '../../store/hub'
import { AgentEditor } from './AgentEditor'
import { Notice, useLibrary } from './common'
import { KnowledgePanel, SkillsPanel } from './LibraryPanels'

type Tab = 'agents' | 'skills' | 'knowledge'
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'agents', label: 'Agents', icon: 'smart_toy' },
  { id: 'skills', label: 'Skills', icon: 'school' },
  { id: 'knowledge', label: 'Knowledge', icon: 'menu_book' },
]

function AgentList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const agents = useHub((s) => s.agents)
  const statuses = useHub((s) => s.statuses)
  return (
    <aside className="flex w-64 shrink-0 flex-col gap-1 overflow-y-auto rounded-3xl bg-surface-container p-3">
      <Button variant="tonal" className="mb-1 w-full" onClick={() => onSelect('new')}>
        <Icon name="add" /> New agent
      </Button>
      {agents.map((a) => (
        <button
          key={a.id}
          onClick={() => onSelect(a.id)}
          className={`flex items-center gap-3 rounded-2xl px-2 py-2 text-left ${selected === a.id ? 'bg-secondary-container text-on-secondary-container' : 'hover:bg-on-surface/5'} ${a.enabled ? '' : 'opacity-60'}`}
        >
          <AgentBadge agent={a} size={32} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{a.name}</span>
            <span className="block truncate text-xs opacity-75">{!a.enabled ? 'Disabled' : a.workflow ? 'Workflow' : `${a.tools.length} tools`}</span>
          </span>
          {statuses[a.id] && statuses[a.id].state !== 'IDLE' && <StateBadge state={statuses[a.id].state} />}
        </button>
      ))}
    </aside>
  )
}

export default function AgentsView() {
  const [tab, setTab] = useState<Tab>('agents')
  const editAgentId = useHub((s) => s.editAgentId)
  const agents = useHub((s) => s.agents)
  const authenticated = useHub((s) => s.auth.authenticated)
  const editAgent = useHub((s) => s.editAgent)
  const library = useLibrary()
  // A just-created agent may not be in the roster until the next snapshot; keep it selected.
  const selected = editAgentId ?? agents[0]?.id ?? 'new'

  if (!authenticated) {
    return (
      <div className="grid h-full place-items-center rounded-3xl bg-surface-container text-sm text-on-surface-variant">
        <div className="text-center">
          <Icon name="lock" className="!text-[32px]" />
          <p className="mt-2">Sign in as the admin to create and edit agents.</p>
          <Button className="mt-3" onClick={() => useHub.getState().setAuth({ loginPrompt: true })}>
            Sign in
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex gap-1 rounded-full bg-surface-container p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`flex h-8 items-center gap-1.5 rounded-full px-4 text-sm font-medium ${tab === t.id ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant hover:bg-on-surface/5'}`}
            >
              <Icon name={t.icon} filled={tab === t.id} className="!text-[18px]" /> {t.label}
              {t.id === 'skills' && library.loaded && <Chip className="!px-1.5 !py-0">{library.skills.length}</Chip>}
              {t.id === 'knowledge' && library.loaded && <Chip className="!px-1.5 !py-0">{library.docs.length}</Chip>}
            </button>
          ))}
        </div>
        {library.error && <Notice tone="error">{library.error}</Notice>}
      </div>
      <div className="min-h-0 flex-1">
        {tab === 'agents' && (
          <div className="flex h-full min-h-0 gap-3">
            <AgentList selected={selected} onSelect={editAgent} />
            <div className="min-w-0 flex-1">
              {library.loaded && (
                <AgentEditor
                  key={selected}
                  agentId={selected}
                  library={library}
                  onSaved={(id) => editAgent(id)}
                  onDeleted={() => editAgent(null)}
                  gotoTab={setTab}
                />
              )}
            </div>
          </div>
        )}
        {tab === 'skills' && library.loaded && <SkillsPanel library={library} />}
        {tab === 'knowledge' && library.loaded && <KnowledgePanel library={library} />}
      </div>
    </div>
  )
}
