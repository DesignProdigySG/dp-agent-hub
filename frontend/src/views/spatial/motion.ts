/**
 * Transient, per-frame agent motion. Lives outside React/Zustand on purpose: avatars read
 * and write it inside useFrame, so movement never triggers a React render.
 */
import type { AgentEvent, AgentStatus, Zone } from '../../types/contract'
import { planPath, slot, ZONE_INFO, zoneAt, type P } from './layout'
import { isFree, navPath, nearestStandable } from './navgrid'

export interface Motion {
  pos: P
  heading: number
  path: P[]
  dest: P
  destZone: Zone
  strolling: boolean // idle wander in progress (walks slowly)
  restUntil: number // clock time the next idle wander may start
}

const fresh = (p: P, zone: Zone): Motion => ({ pos: { ...p }, heading: 0, path: [], dest: p, destZone: zone, strolling: false, restUntil: 0 })

/** A hand-off playing out: the sender walks over, the two face each other and exchange two lines. */
export interface Talk {
  from: string
  to: string
  lineFrom: string
  lineTo: string
  startedAt: number | null // clock time the sender arrived; null while still walking over
  back: P // where the sender returns to afterwards
}

export const SAY_FROM_S = 2.5
export const SAY_TO_S = 2

const motions = new Map<string, Motion>()
const talks = new Map<string, Talk>() // by sender
let order: string[] = []

export function setAgentOrder(ids: string[]) {
  order = ids
}

const indexOf = (id: string) => Math.max(order.indexOf(id), 0)

export function getMotion(id: string): Motion | undefined {
  return motions.get(id)
}

/** Snapshot: place agents directly at their current zone slot. */
export function placeAll(statuses: AgentStatus[]) {
  talks.clear()
  for (const s of statuses) {
    const p = nearestStandable(slot(s.zone, indexOf(s.agent_id), order.length))
    motions.set(s.agent_id, fresh(p, s.zone))
  }
}

export function getTalk(id: string): Talk | undefined {
  return talks.get(id)
}

/** Either side of a conversation in progress (they stand still and face each other). */
export function inTalk(id: string): boolean {
  for (const t of talks.values()) if (t.from === id || t.to === id) return true
  return false
}

/** Everyone in a conversation right now, sorted. */
export function talkers(): string[] {
  const ids = new Set<string>()
  for (const t of talks.values()) ids.add(t.from).add(t.to)
  return [...ids].sort()
}

/** A spot beside the receiver, on the sender's side, to stop and talk at. */
function meetingSpot(from: P, to: P): P {
  const dx = from.x - to.x
  const dz = from.z - to.z
  const d = Math.hypot(dx, dz) || 1
  return nearestStandable({ x: to.x + (dx / d) * 1.6, z: to.z + (dz / d) * 1.6 })
}

function startTalk(ev: AgentEvent) {
  const info = ev.handoff!
  const from = motions.get(ev.agent_id)
  const to = motions.get(info.to_agent_id)
  if (!from || !to) return
  talks.delete(ev.agent_id)
  const spot = meetingSpot(from.pos, to.dest)
  const path = navPath(from.pos, spot)
  if (!path) return
  from.strolling = false
  from.path = path
  from.dest = spot
  talks.set(ev.agent_id, { from: ev.agent_id, to: info.to_agent_id, lineFrom: info.line_from, lineTo: info.line_to, startedAt: null, back: { ...from.pos } })
}

/**
 * Advance every conversation. Returns the lines being said right now, by agent. A sender
 * who arrives says their line, the receiver answers, then the sender walks back.
 */
export function tickTalks(now: number): Record<string, string> {
  const said: Record<string, string> = {}
  for (const t of talks.values()) {
    const from = motions.get(t.from)
    const to = motions.get(t.to)
    if (!from || !to) {
      talks.delete(t.from)
      continue
    }
    if (t.startedAt === null) {
      if (from.path.length) continue // still on the way
      t.startedAt = now
    }
    const facing = Math.atan2(to.pos.x - from.pos.x, to.pos.z - from.pos.z)
    if (!from.path.length) from.heading = facing
    if (!to.path.length) to.heading = facing + Math.PI
    const elapsed = now - t.startedAt
    if (elapsed < SAY_FROM_S) said[t.from] = t.lineFrom
    else if (elapsed < SAY_FROM_S + SAY_TO_S) said[t.to] = t.lineTo
    else {
      talks.delete(t.from)
      const path = navPath(from.pos, t.back)
      if (path) {
        from.path = path
        from.dest = t.back
      }
    }
  }
  return said
}

/** Route an agent toward the event's target zone if it isn't already headed there. */
export function onAgentEvent(ev: AgentEvent) {
  if (ev.action === 'handoff' && ev.handoff) {
    startTalk(ev)
    return
  }
  const target = nearestStandable(slot(ev.target_zone, indexOf(ev.agent_id), order.length))
  const m = motions.get(ev.agent_id)
  if (!m) {
    motions.set(ev.agent_id, fresh(target, ev.target_zone))
    return
  }
  if (m.destZone === ev.target_zone) return
  talks.delete(ev.agent_id) // real work takes over a conversation
  m.strolling = false
  // around the decor; the corridor graph only if the floor has no way through
  m.path = navPath(m.pos, target) ?? planPath(zoneAt(m.pos), ev.target_zone, target)
  m.dest = m.path[m.path.length - 1] ?? target
  m.destZone = ev.target_zone
}

/** The layout changed: agents on the move find a new way around it. */
export function replanAll() {
  for (const m of motions.values()) {
    if (!m.path.length) continue
    const path = navPath(m.pos, m.dest)
    if (path) m.path = path
  }
}

/** Advance along the path. Returns true while moving. */
export function step(m: Motion, dt: number, speed = 4.5): boolean {
  let budget = speed * dt
  while (budget > 0 && m.path.length) {
    const next = m.path[0]
    const dx = next.x - m.pos.x
    const dz = next.z - m.pos.z
    const d = Math.hypot(dx, dz)
    if (d > 1e-4) m.heading = Math.atan2(dx, dz)
    if (d <= budget) {
      m.pos = { ...next }
      m.path.shift()
      budget -= d
    } else {
      m.pos = { x: m.pos.x + (dx / d) * budget, z: m.pos.z + (dz / d) * budget }
      budget = 0
    }
  }
  return m.path.length > 0
}

export const WALK_SPEED = 4.5
export const STROLL_SPEED = 1.3

/** A free spot in `zone` to stroll to: anywhere on its floor clear of decor and other agents. */
function strollSpot(id: string, zone: Zone): P | null {
  const c = ZONE_INFO[zone].center
  for (let i = 0; i < 16; i++) {
    const p = { x: c.x + (Math.random() * 2 - 1) * 3.8, z: c.z + (Math.random() * 2 - 1) * 3.8 }
    const crowded = [...motions].some(([other, m]) => other !== id && Math.hypot(m.dest.x - p.x, m.dest.z - p.z) < 1.4)
    if (!crowded && isFree(p)) return p
  }
  return null
}

/**
 * Idle life: an agent with nothing to do strolls to a free spot in its zone, rests a few
 * seconds, and goes again. Real work (onAgentEvent) always takes over.
 */
export function wander(id: string, m: Motion, now: number) {
  if (m.path.length) return
  if (m.restUntil === 0 || m.strolling) {
    // first idle moment (stagger agents), or just arrived: rest
    m.strolling = false
    m.restUntil = now + (m.restUntil === 0 ? Math.random() * 4 : 2.5 + Math.random() * 5)
    return
  }
  if (now < m.restUntil) return
  const spot = strollSpot(id, m.destZone)
  const path = spot && navPath(m.pos, spot)
  if (!spot || !path) {
    m.restUntil = now + 2
    return
  }
  m.path = path
  m.dest = spot
  m.strolling = true
}
