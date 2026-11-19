/**
 * Sims-style thought clouds: what an agent is thinking about, at a glance, over its head.
 * One cloud at a time, the most important first: an error, a request for help, a
 * conversation, work in progress, then news (a finished task you haven't looked at yet).
 */
import { create } from 'zustand'

import type { AgentState, TaskOut, Zone } from '../../types/contract'

export type Thought = 'error' | 'help' | 'talking' | 'working' | 'news'

/** Material Symbols icon in the cloud; working shows what it's working on (its zone). */
export const THOUGHT_ICON: Record<Exclude<Thought, 'working'>, string> = {
  error: 'thunderstorm',
  help: 'priority_high',
  talking: 'forum',
  news: 'lightbulb',
}
export const WORK_ICON: Record<Zone, string> = {
  database: 'database',
  campaigns: 'campaign',
  design_studio: 'palette',
  break_room: 'coffee',
}

export function thoughtFor(a: { state: AgentState; talking: boolean; saying: boolean; news: boolean }): Thought | null {
  if (a.saying) return null // the speech bubble says it
  if (a.state === 'ERROR') return 'error'
  if (a.state === 'NEEDS_HELP') return 'help'
  if (a.talking) return 'talking'
  if (a.state === 'BUSY') return 'working'
  if (a.news && a.state === 'IDLE') return 'news'
  return null
}

/** Tasks finished since this page opened count as news until you open the agent. */
const OPENED_AT = Date.now()

interface SeenState {
  seen: Record<string, true>
  markSeen: (taskIds: string[]) => void
}

export const useSeen = create<SeenState>()((set) => ({
  seen: {},
  markSeen: (ids) => set((s) => (ids.every((id) => s.seen[id]) ? s : { seen: { ...s.seen, ...Object.fromEntries(ids.map((id) => [id, true as const])) } })),
}))

/** The agent's finished tasks you haven't seen (finished after the page opened). */
export function newsFor(agentId: string, tasks: Record<string, TaskOut>, seen: Record<string, true>, openedAt = OPENED_AT): string[] {
  return Object.values(tasks)
    .filter((t) => t.agent_id === agentId && t.status === 'done' && !seen[t.id] && Date.parse(t.updated_at) > openedAt)
    .map((t) => t.id)
}
