import type { Zone } from '../../types/contract'

/** A point on the floor plane (three.js x / z). */
export interface P {
  x: number
  z: number
}

export const ZONES: Zone[] = ['database', 'campaigns', 'design_studio', 'break_room']

export const ZONE_SIZE = 9

export const ZONE_INFO: Record<Zone, { label: string; center: P; door: string; kpis: string[] }> = {
  database: {
    label: 'The Database',
    center: { x: -7, z: -7 },
    door: 'door_database',
    kpis: ['uniqueness', 'completeness', 'normalization', 'contactability'],
  },
  campaigns: {
    label: 'Campaigns',
    center: { x: 7, z: -7 },
    door: 'door_campaigns',
    kpis: ['active_runs', 'queue_size'],
  },
  design_studio: {
    label: 'Design Studio',
    center: { x: 7, z: 7 },
    door: 'door_design_studio',
    kpis: ['total_assets', 'approval_rate'],
  },
  break_room: {
    label: 'Break Room (HQ)',
    center: { x: -7, z: 7 },
    door: 'door_break_room',
    kpis: [], // computed from agent states: active vs idle, alerts
  },
}

/**
 * Walkable waypoint graph. Doors sit at each zone's inner corner; corridors run between
 * adjacent doors and through the central hub. Zone centers connect only to their own door.
 */
export const NODES: Record<string, P> = {
  hub: { x: 0, z: 0 },
  door_database: { x: -2.6, z: -2.6 },
  door_campaigns: { x: 2.6, z: -2.6 },
  door_design_studio: { x: 2.6, z: 2.6 },
  door_break_room: { x: -2.6, z: 2.6 },
  ...Object.fromEntries(ZONES.map((z) => [`zone_${z}`, ZONE_INFO[z].center])),
}

const EDGES: [string, string][] = [
  ['hub', 'door_database'],
  ['hub', 'door_campaigns'],
  ['hub', 'door_design_studio'],
  ['hub', 'door_break_room'],
  ['door_database', 'door_campaigns'],
  ['door_campaigns', 'door_design_studio'],
  ['door_design_studio', 'door_break_room'],
  ['door_break_room', 'door_database'],
  ...ZONES.map((z): [string, string] => [`zone_${z}`, ZONE_INFO[z].door]),
]

const NEIGHBORS: Record<string, string[]> = {}
for (const [a, b] of EDGES) {
  ;(NEIGHBORS[a] ??= []).push(b)
  ;(NEIGHBORS[b] ??= []).push(a)
}

export const dist = (a: P, b: P) => Math.hypot(a.x - b.x, a.z - b.z)

/** A* over the waypoint graph. Returns node ids from start to goal inclusive. */
export function astar(start: string, goal: string): string[] {
  const open = new Set([start])
  const came: Record<string, string> = {}
  const g: Record<string, number> = { [start]: 0 }
  const f: Record<string, number> = { [start]: dist(NODES[start], NODES[goal]) }
  while (open.size) {
    let cur = ''
    for (const n of open) if (!cur || f[n] < f[cur]) cur = n
    if (cur === goal) {
      const path = [cur]
      while (came[path[0]]) path.unshift(came[path[0]])
      return path
    }
    open.delete(cur)
    for (const nb of NEIGHBORS[cur] ?? []) {
      const tentative = g[cur] + dist(NODES[cur], NODES[nb])
      if (tentative < (g[nb] ?? Infinity)) {
        came[nb] = cur
        g[nb] = tentative
        f[nb] = tentative + dist(NODES[nb], NODES[goal])
        open.add(nb)
      }
    }
  }
  return []
}

/** Each agent gets its own spot on a ring inside every zone so they never overlap. */
export function slot(zone: Zone, agentIndex: number, agentCount = 6): P {
  const c = ZONE_INFO[zone].center
  const angle = (agentIndex / Math.max(agentCount, 1)) * Math.PI * 2 + Math.PI / 4
  return { x: c.x + Math.cos(angle) * 2.2, z: c.z + Math.sin(angle) * 2.2 }
}

/** Floor points to walk from somewhere in `fromZone` to `target` inside `toZone`. */
export function planPath(fromZone: Zone, toZone: Zone, target: P): P[] {
  if (fromZone === toZone) return [target]
  const nodes = astar(ZONE_INFO[fromZone].door, ZONE_INFO[toZone].door)
  return [...nodes.map((n) => NODES[n]), target]
}

/** Which zone a floor point is in (nearest zone center). */
export function zoneAt(p: P): Zone {
  return ZONES.reduce((best, z) =>
    dist(p, ZONE_INFO[z].center) < dist(p, ZONE_INFO[best].center) ? z : best,
  )
}
