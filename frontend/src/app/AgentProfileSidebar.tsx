import { lazy, Suspense } from 'react'

import { AgentBadge } from '../components/AgentBadge'
import { AgentReportPanel } from './AgentReportPanel'
import { Button, Chip, Icon, StateBadge, relativeTime } from '../components/ui'
import { useHub } from '../store/hub'
import { pendingApprovalFor } from '../store/reduce'
import type { AgentProfile } from '../types/contract'
import { ZONE_INFO } from '../views/spatial/layout'

// three.js only loads when a profile is opened
const AvatarHeader = lazy(() => import('./AvatarHeader'))

function AgentList() {
  const agents = useHub((s) => s.agents)
  const statuses = useHub((s) => s.statuses)
  const select = useHub((s) => s.selectAgent)
  return (
    <div className="space-y-1">
      <h2 className="px-2 pb-2 text-sm font-semibold">Agents</h2>
      {!agents.length && <p className="px-2 text-sm text-on-surface-variant">No agents yet. Create one under Agents.</p>}
      {agents.map((a) => {
        const st = statuses[a.id]
        return (
          <button key={a.id} onClick={() => select(a.id)} className="flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left hover:bg-on-surface/5">
            <AgentBadge agent={a} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{a.name}</span>
              <span className="block truncate text-xs text-on-surface-variant">{st?.status_text ?? a.title}</span>
            </span>
            {st && <StateBadge state={st.state} />}
          </button>
        )
      })}
    </div>
  )
}

function AgentDetail({ agent }: { agent: AgentProfile }) {
  const status = useHub((s) => s.statuses[agent.id])
  const approval = useHub((s) => pendingApprovalFor(s.approvals, s.statuses[agent.id]?.task_id))
  const log = useHub((s) => s.log)
  const { selectAgent, review, openNewTask, editAgent } = useHub.getState()
  const isAdmin = useHub((s) => s.auth.authenticated)
  const recent = log.filter((e) => e.agent_id === agent.id && e.action !== 'travel').slice(-8).reverse()

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <button onClick={() => selectAgent(null)} className="flex items-center gap-1 text-sm text-on-surface-variant hover:text-on-surface">
          <Icon name="arrow_back" /> All agents
        </button>
        <span className="flex">
          {isAdmin && (
            <Button variant="text" onClick={() => editAgent(agent.id)}>
              <Icon name="edit" /> Edit
            </Button>
          )}
          {agent.enabled && (
            <Button variant="text" onClick={() => openNewTask({ agentId: agent.id })}>
              <Icon name="add_task" /> Assign
            </Button>
          )}
        </span>
      </div>
      <Suspense fallback={<div className="h-36 rounded-2xl bg-surface-container-high" />}>
        <AvatarHeader agent={agent} />
      </Suspense>
      <div>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{agent.name}</h2>
          {status && <StateBadge state={status.state} />}
        </div>
        <p className="text-sm text-on-surface-variant">{agent.title}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Chip>
            <Icon name="psychology" className="!text-[14px]" /> {agent.model_tier} tier
          </Chip>
          {agent.channels.map((c) => (
            <Chip key={c}>
              <Icon name={c === 'rest' ? 'api' : 'extension'} className="!text-[14px]" /> {c.toUpperCase()}
            </Chip>
          ))}
          <Chip>
            <Icon name="location_on" className="!text-[14px]" /> {ZONE_INFO[status?.zone ?? agent.home_zone].label}
          </Chip>
          {agent.memory_enabled && (
            <Chip>
              <Icon name="neurology" className="!text-[14px]" /> Memory
            </Chip>
          )}
          {!agent.enabled && <Chip>Disabled</Chip>}
        </div>
      </div>

      {status && status.state !== 'IDLE' && (
        <div className="rounded-2xl bg-surface-container px-3 py-2.5 text-sm">{status.status_text}</div>
      )}
      {approval && (
        <Button variant="danger" className="w-full" onClick={() => review(approval.id)}>
          <Icon name="front_hand" filled /> Review pending approval
        </Button>
      )}

      <AgentReportPanel agentId={agent.id} color={agent.color} />

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">Tools</h3>
        {agent.workflow ? (
          <p className="text-sm text-on-surface-variant">Code-defined workflow: fixed steps, with its one Marketo write behind guardrails.</p>
        ) : agent.tools.length ? (
          <div className="flex flex-wrap gap-1">
            {agent.tools.map((t) => (
              <Chip key={t} className="font-mono">
                {t}
              </Chip>
            ))}
          </div>
        ) : (
          <p className="text-sm text-on-surface-variant">No Marketo tools.</p>
        )}
      </section>

      {[
        { title: 'Skills', icon: 'school', items: agent.skills },
        { title: 'Knowledge base', icon: 'description', items: agent.knowledge },
      ].map((sec) => (
        <section key={sec.title}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">{sec.title}</h3>
          {sec.items.length ? (
            <ul className="space-y-1">
              {sec.items.map((k) => (
                <li key={k} className="flex items-center gap-2 text-sm">
                  <Icon name={sec.icon} className="text-on-surface-variant" /> {k}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-on-surface-variant">None attached.</p>
          )}
        </section>
      ))}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">Recent activity</h3>
        {recent.length ? (
          <ol className="space-y-1.5">
            {recent.map((e, i) => (
              <li key={i} className="flex gap-2 text-xs">
                <span className="w-14 shrink-0 text-on-surface-variant">{e.ts ? relativeTime(e.ts) : ''}</span>
                <span>{e.status_text}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-on-surface-variant">Nothing yet.</p>
        )}
      </section>
    </div>
  )
}

export function AgentProfileSidebar() {
  const agent = useHub((s) => s.agents.find((a) => a.id === s.selectedAgentId))
  return (
    <aside className="hidden w-80 shrink-0 overflow-y-auto rounded-3xl bg-surface-container p-4 lg:block">
      {agent ? <AgentDetail agent={agent} /> : <AgentList />}
    </aside>
  )
}
