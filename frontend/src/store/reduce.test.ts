import { describe, expect, it } from 'vitest'

import type { AgentEvent, TaskOut } from '../types/contract'
import { LOG_LIMIT, emptyHub, pendingApprovalFor, reduce, type HubData } from './reduce'

const task = (id: string, status: TaskOut['status'] = 'queued'): TaskOut => ({
  id, title: id, description: '', agent_id: 'list_builder', status, params: {}, result: '',
  scheduled_for: null, schedule_id: null, run: 0, history: [], archived_at: null,
  created_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:00Z',
})

const event = (metrics: Record<string, string | number>): AgentEvent => ({
  type: 'agent_event', agent_id: 'list_builder', task_id: 't1', action: 'validate_records',
  source_zone: 'break_room', target_zone: 'database', status_text: 'Auditing...', state: 'BUSY',
  metrics, ts: '2026-11-03T00:00:00Z', handoff: null,
})

const apply = (s: HubData, ...msgs: Parameters<typeof reduce>[1][]) =>
  msgs.reduce((acc, m) => ({ ...acc, ...reduce(acc, m) }), s)

describe('reduce', () => {
  it('marks the hub loaded on a snapshot, even with no agents yet', () => {
    expect(emptyHub.loaded).toBe(false)
    const s = apply(emptyHub, {
      type: 'snapshot', agents: [], statuses: [], tasks: [], approvals: [], governor: null, marketo_mode: 'demo',
    } as unknown as Parameters<typeof reduce>[1])
    expect(s.loaded).toBe(true)
    expect(s.agents).toEqual([])
  })

  it('upserts and deletes tasks', () => {
    let s = apply(emptyHub, { type: 'task_updated', task: task('t1') })
    s = apply(s, { type: 'task_updated', task: task('t1', 'in_progress') })
    expect(s.tasks.t1.status).toBe('in_progress')
    s = apply(s, { type: 'task_deleted', task_id: 't1' })
    expect(s.tasks).toEqual({})
  })

  it('merges agent metrics across events and moves the agent to the target zone', () => {
    const s = apply(emptyHub, event({ uniqueness: '90.0%' }), event({ completeness: '80.0%' }))
    expect(s.statuses.list_builder.zone).toBe('database')
    expect(s.statuses.list_builder.metrics).toEqual({ uniqueness: '90.0%', completeness: '80.0%' })
  })

  it('caps the activity log', () => {
    let s = emptyHub
    for (let i = 0; i < LOG_LIMIT + 50; i++) s = apply(s, event({ n: i }))
    expect(s.log).toHaveLength(LOG_LIMIT)
    expect(s.log.at(-1)!.metrics).toEqual({ n: LOG_LIMIT + 49 })
  })

  it('finds only pending approvals for a task', () => {
    const base = {
      id: 'a1', task_id: 't1', agent_id: 'list_builder', action: 'x', summary: '', details: {},
      comment: '', created_at: '', decided_at: null,
    }
    expect(pendingApprovalFor({ a1: { ...base, status: 'pending' } }, 't1')?.id).toBe('a1')
    expect(pendingApprovalFor({ a1: { ...base, status: 'approved' } }, 't1')).toBeUndefined()
    expect(pendingApprovalFor({}, null)).toBeUndefined()
  })
})
