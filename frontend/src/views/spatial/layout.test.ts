import { describe, expect, it } from 'vitest'

import { NODES, ZONE_INFO, ZONES, astar, dist, planPath, slot, zoneAt } from './layout'
import { onAgentEvent, getMotion, placeAll, setAgentOrder, step } from './motion'
import type { AgentEvent } from '../../types/contract'

describe('waypoint graph', () => {
  it('routes between every pair of zone doors', () => {
    for (const a of ZONES)
      for (const b of ZONES) {
        const path = astar(ZONE_INFO[a].door, ZONE_INFO[b].door)
        expect(path[0]).toBe(ZONE_INFO[a].door)
        expect(path.at(-1)).toBe(ZONE_INFO[b].door)
      }
  })

  it('takes the corridor between adjacent zones rather than detouring', () => {
    expect(astar('door_database', 'door_campaigns')).toEqual(['door_database', 'door_campaigns'])
  })

  it('crosses diagonally through the hub', () => {
    expect(astar('door_database', 'door_design_studio')).toEqual(['door_database', 'hub', 'door_design_studio'])
  })

  it('plans door-to-door and ends at the target slot', () => {
    const target = slot('database', 0)
    const path = planPath('break_room', 'database', target)
    expect(path[0]).toEqual(NODES.door_break_room)
    expect(path.at(-1)).toEqual(target)
    expect(planPath('database', 'database', target)).toEqual([target])
  })

  it('gives each agent a distinct slot inside its zone', () => {
    const slots = Array.from({ length: 6 }, (_, i) => slot('campaigns', i))
    for (const s of slots) expect(zoneAt(s)).toBe('campaigns')
    for (let i = 0; i < slots.length; i++)
      for (let j = i + 1; j < slots.length; j++) expect(dist(slots[i], slots[j])).toBeGreaterThan(1)
  })
})

describe('motion', () => {
  const ev = (target: AgentEvent['target_zone']): AgentEvent => ({
    type: 'agent_event', agent_id: 'a1', task_id: null, action: 'travel', source_zone: 'break_room',
    target_zone: target, status_text: '', state: 'TRAVELING', metrics: {}, ts: '', handoff: null,
  })

  it('walks an agent from the break room to its database slot', () => {
    setAgentOrder(['a1'])
    placeAll([{ agent_id: 'a1', zone: 'break_room', state: 'IDLE', status_text: '', task_id: null, metrics: {} }])
    onAgentEvent(ev('database'))
    const m = getMotion('a1')!
    expect(m.path.length).toBeGreaterThan(1)
    for (let i = 0; i < 1000 && step(m, 0.05); i++);
    expect(m.path).toEqual([])
    expect(m.pos).toEqual(slot('database', 0, 1))
  })

  it('ignores repeat events for the zone it is already headed to', () => {
    onAgentEvent(ev('campaigns'))
    const path = [...getMotion('a1')!.path]
    onAgentEvent(ev('campaigns'))
    expect(getMotion('a1')!.path).toEqual(path)
  })
})
