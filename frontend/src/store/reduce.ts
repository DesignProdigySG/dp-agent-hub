import type {
  AgentEvent,
  AgentProfile,
  AgentStatus,
  ApprovalOut,
  GovernorStats,
  ServerMessage,
  TaskOut,
} from '../types/contract'

export const LOG_LIMIT = 300

export interface HubData {
  connected: boolean
  loaded: boolean // a snapshot has arrived (the roster itself may be empty)
  mode: 'demo' | 'live' | null
  agents: AgentProfile[]
  statuses: Record<string, AgentStatus>
  tasks: Record<string, TaskOut>
  approvals: Record<string, ApprovalOut>
  governor: GovernorStats | null
  log: AgentEvent[]
}

export const emptyHub: HubData = {
  connected: false,
  loaded: false,
  mode: null,
  agents: [],
  statuses: {},
  tasks: {},
  approvals: {},
  governor: null,
  log: [],
}

const byId = <T extends { id: string }>(rows: T[]) => Object.fromEntries(rows.map((r) => [r.id, r]))

/** Pure reducer from a server message to the next hub data. */
export function reduce(state: HubData, msg: ServerMessage): Partial<HubData> {
  switch (msg.type) {
    case 'snapshot':
      return {
        loaded: true,
        mode: msg.marketo_mode,
        agents: msg.agents,
        statuses: Object.fromEntries(msg.statuses.map((s) => [s.agent_id, s])),
        tasks: byId(msg.tasks),
        approvals: byId(msg.approvals),
        governor: msg.governor,
      }
    case 'agent_event': {
      const prev = state.statuses[msg.agent_id]
      const status: AgentStatus = {
        agent_id: msg.agent_id,
        zone: msg.target_zone,
        state: msg.state,
        status_text: msg.status_text,
        task_id: msg.task_id,
        metrics: { ...prev?.metrics, ...msg.metrics },
      }
      return {
        statuses: { ...state.statuses, [msg.agent_id]: status },
        log: [...state.log.slice(-(LOG_LIMIT - 1)), msg],
      }
    }
    case 'task_updated':
      return { tasks: { ...state.tasks, [msg.task.id]: msg.task } }
    case 'task_deleted': {
      const tasks = { ...state.tasks }
      delete tasks[msg.task_id]
      return { tasks }
    }
    case 'approval_updated':
      return { approvals: { ...state.approvals, [msg.approval.id]: msg.approval } }
    case 'governor':
      return { governor: msg.stats }
  }
}

export function pendingApprovalFor(approvals: Record<string, ApprovalOut>, taskId?: string | null) {
  if (!taskId) return undefined
  return Object.values(approvals).find((a) => a.task_id === taskId && a.status === 'pending')
}
