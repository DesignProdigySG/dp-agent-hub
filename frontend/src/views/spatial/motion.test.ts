import { beforeEach, describe, expect, it } from 'vitest'

import { STUD_W } from './bricks'
import { ZONE_INFO, type P } from './layout'
import { getMotion, getTalk, inTalk, onAgentEvent, placeAll, replanAll, SAY_FROM_S, SAY_TO_S, setAgentOrder, step, STROLL_SPEED, tickTalks, WALK_SPEED, wander } from './motion'
import { isFree, navPath, setObstacles } from './navgrid'
import { footprint, type Placed } from './placement'

const idle = (id: string) => ({ agent_id: id, zone: 'break_room' as const, state: 'IDLE' as const, status_text: '', task_id: null, metrics: {} })

/** Every point along a path (and the segments between) keeps clear of every piece. */
function clearOf(start: P, path: P[], pieces: Placed[]) {
  let a = start
  for (const b of path) {
    for (let t = 0; t <= 1; t += 0.02) {
      const x = (a.x + (b.x - a.x) * t) / STUD_W
      const z = (a.z + (b.z - a.z) * t) / STUD_W
      for (const p of pieces) {
        const [w, d] = footprint(p)
        if (Math.abs(x - p.x) < w / 2 + 0.3 && Math.abs(z - p.z) < d / 2 + 0.3) return false
      }
    }
    a = b
  }
  return true
}

describe('idle wandering', () => {
  beforeEach(() => setObstacles([]))

  it('rests, strolls inside the break room, and yields to real work', () => {
    setAgentOrder(['a'])
    placeAll([idle('a')])
    const m = getMotion('a')!
    wander('a', m, 10) // first idle moment: staggered rest
    expect(m.path).toHaveLength(0)
    wander('a', m, 100) // rested: off it goes
    expect(m.strolling).toBe(true)
    const c = ZONE_INFO.break_room.center
    expect(Math.abs(m.dest.x - c.x)).toBeLessThanOrEqual(3.8) // anywhere free in the zone
    expect(Math.abs(m.dest.z - c.z)).toBeLessThanOrEqual(3.8)
    for (let i = 0; i < 200 && step(m, 0.05, STROLL_SPEED); i++);
    wander('a', m, 101) // arrived: rests again
    expect(m.strolling).toBe(false)
    expect(m.restUntil).toBeGreaterThan(101)

    m.restUntil = 0.5
    wander('a', m, 200)
    onAgentEvent({ type: 'agent_event', agent_id: 'a', task_id: 't', action: 'travel', source_zone: 'break_room', target_zone: 'database', status_text: '', state: 'TRAVELING', metrics: {}, ts: '', handoff: null })
    expect(m.strolling).toBe(false)
    expect(m.destZone).toBe('database')
  })

  it('stays put when every spot is blocked', () => {
    setAgentOrder(['b'])
    placeAll([idle('b')])
    const m = getMotion('b')!
    // cover the whole break room in bricks
    const zone = ZONE_INFO.break_room.center
    const cover: Placed[] = []
    for (let x = -8; x < 8; x += 2) for (let z = -8; z < 8; z += 2) cover.push({ piece: 'round-hq-brick-2x2', color: 'red', x: zone.x / STUD_W + x + 1, y: 1, z: zone.z / STUD_W + z + 1, rot: 0 })
    setObstacles(cover)
    m.restUntil = 1
    wander('b', m, 5)
    expect(m.path).toHaveLength(0)
    expect(m.restUntil).toBe(7)
  })
})

describe('walking around bricks', () => {
  // a wall across the walkway between the break room and the database
  const wall: Placed[] = [-3, -1, 1, 3].map((x) => ({ piece: 'round-hq-brick-2x2', color: 'black', x, y: 1, z: 6, rot: 0 }))

  it('routes around a wall instead of through it', () => {
    setObstacles(wall)
    const from = { x: 0, z: 12 * STUD_W }
    const to = { x: 0, z: 0.5 * STUD_W - 4 * STUD_W }
    const path = navPath(from, to)!
    expect(path).not.toBeNull()
    expect(clearOf(from, path, wall)).toBe(true)
    expect(path.at(-1)).toEqual(to)
  })

  it('gets agents out of a brick dropped on them, and to the nearest free spot of a blocked target', () => {
    setObstacles(wall)
    const inside = { x: -1 * STUD_W, z: 6 * STUD_W }
    expect(isFree(inside)).toBe(false)
    const path = navPath(inside, { x: 1 * STUD_W, z: 6 * STUD_W })! // into the wall too
    expect(path).not.toBeNull()
    expect(isFree(path.at(-1)!)).toBe(true)
  })

  it('agents on their way re-plan when the layout changes', () => {
    setObstacles([])
    setAgentOrder(['c'])
    placeAll([idle('c')])
    const m = getMotion('c')!
    onAgentEvent({ type: 'agent_event', agent_id: 'c', task_id: 't', action: 'travel', source_zone: 'break_room', target_zone: 'design_studio', status_text: '', state: 'TRAVELING', metrics: {}, ts: '', handoff: null })
    step(m, 0.1, WALK_SPEED)
    // a wall goes up across the walkway they're about to use
    const block: Placed[] = [-6, -4, -2, 0, 2, 4, 6].map((x) => ({ piece: 'round-hq-brick-2x2', color: 'black', x: 6, y: 1, z: x, rot: 0 }))
    setObstacles(block)
    replanAll()
    expect(clearOf(m.pos, m.path, block)).toBe(true)
    for (let i = 0; i < 2000 && step(m, 0.05, WALK_SPEED); i++);
    expect(Math.hypot(m.pos.x - m.dest.x, m.pos.z - m.dest.z)).toBeLessThan(0.01)
  })
})

describe('hand-offs', () => {
  const handoff = (from: string, to: string) =>
    onAgentEvent({ type: 'agent_event', agent_id: from, task_id: 't', action: 'handoff', source_zone: 'database', target_zone: 'database', status_text: '', state: 'BUSY', metrics: {}, ts: '', handoff: { to_agent_id: to, task_id: 't2', line_from: '12 leads ready for you', line_to: 'On it' } })

  it('sends the sender over, plays both lines in turn, then walks them back', () => {
    setObstacles([])
    setAgentOrder(['doc', 'qual'])
    placeAll([{ ...idle('doc'), zone: 'database' }, idle('qual')])
    const doc = getMotion('doc')!
    const qual = getMotion('qual')!
    const home = { ...doc.pos }
    handoff('doc', 'qual')
    expect(getTalk('doc')).toBeDefined()
    expect(inTalk('qual')).toBe(true)
    expect(doc.path.length).toBeGreaterThan(0)
    expect(tickTalks(0)).toEqual({}) // nothing said while walking over
    for (let i = 0; i < 2000 && step(doc, 0.05, WALK_SPEED); i++);
    expect(Math.hypot(doc.pos.x - qual.pos.x, doc.pos.z - qual.pos.z)).toBeLessThan(2.5)
    expect(tickTalks(10)).toEqual({ doc: '12 leads ready for you' })
    // they face each other
    expect(Math.cos(doc.heading - qual.heading)).toBeCloseTo(-1) // opposite headings
    expect(tickTalks(10 + SAY_FROM_S + 0.1)).toEqual({ qual: 'On it' })
    expect(tickTalks(10 + SAY_FROM_S + SAY_TO_S + 0.1)).toEqual({})
    expect(getTalk('doc')).toBeUndefined()
    expect(doc.dest).toEqual(home) // heading back to where they were
    expect(doc.destZone).toBe('database')
  })

  it('yields to real work: a travel event ends the conversation', () => {
    setObstacles([])
    setAgentOrder(['doc', 'qual'])
    placeAll([{ ...idle('doc'), zone: 'database' }, idle('qual')])
    handoff('doc', 'qual')
    onAgentEvent({ type: 'agent_event', agent_id: 'doc', task_id: 't', action: 'travel', source_zone: 'database', target_zone: 'break_room', status_text: '', state: 'TRAVELING', metrics: {}, ts: '', handoff: null })
    expect(getTalk('doc')).toBeUndefined()
    expect(getMotion('doc')!.destZone).toBe('break_room')
  })
})
