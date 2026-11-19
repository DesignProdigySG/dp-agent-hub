/**
 * Where agents can walk: a grid over the floor (half-stud cells) with every brick's footprint
 * blocked, plus a margin for the agent's body. Paths are A* over the grid (no cutting corners
 * past bricks), then straightened wherever there's a clear line, so agents walk naturally
 * around decor instead of through it.
 */
import { STUD_W } from './bricks'
import type { P } from './layout'
import { floorAt, footprint, type Placed } from './placement'

const CELL = 0.5 // studs per cell
const MIN = -21 // studs: the floor (zones + walkway) lies within ±20
const N = (2 * -MIN) / CELL
const MARGIN = 0.55 // studs kept clear around a brick: about an agent's half-width

let walkable = new Uint8Array(N * N)

const idx = (i: number, j: number) => j * N + i
const inside = (i: number, j: number) => i >= 0 && j >= 0 && i < N && j < N
const studOf = (i: number) => MIN + (i + 0.5) * CELL // cell center, studs
const cellOf = (stud: number) => Math.floor((stud - MIN) / CELL)

/** Rebuild the grid from the decor (and any fixed pieces, like the centerpiece). */
export function setObstacles(pieces: Placed[]) {
  const grid = new Uint8Array(N * N)
  for (let j = 0; j < N; j++)
    for (let i = 0; i < N; i++) {
      const x = studOf(i)
      const z = studOf(j)
      // on the floor with room to spare (agents don't teeter on the edge)
      const onFloor = [0, MARGIN, -MARGIN].every((d) => floorAt(x + d, z) === 1 && floorAt(x, z + d) === 1)
      grid[idx(i, j)] = onFloor ? 1 : 0
    }
  for (const p of pieces) {
    const [w, d] = footprint(p)
    const i0 = cellOf(p.x - w / 2 - MARGIN)
    const i1 = cellOf(p.x + w / 2 + MARGIN - 1e-6)
    const j0 = cellOf(p.z - d / 2 - MARGIN)
    const j1 = cellOf(p.z + d / 2 + MARGIN - 1e-6)
    for (let j = Math.max(j0, 0); j <= Math.min(j1, N - 1); j++)
      for (let i = Math.max(i0, 0); i <= Math.min(i1, N - 1); i++) grid[idx(i, j)] = 0
  }
  walkable = grid
}

const toCell = (p: P): [number, number] => [cellOf(p.x / STUD_W), cellOf(p.z / STUD_W)]
const toWorld = (i: number, j: number): P => ({ x: studOf(i) * STUD_W, z: studOf(j) * STUD_W })
const free = (i: number, j: number) => inside(i, j) && walkable[idx(i, j)] === 1

/** Whether an agent can stand at a floor point (world units). */
export function isFree(p: P): boolean {
  return free(...toCell(p))
}

/** The nearest standable cell to a point (breadth-first), or null if there's none near. */
function nearestFree(i: number, j: number, maxRadius = 24): [number, number] | null {
  if (free(i, j)) return [i, j]
  for (let r = 1; r <= maxRadius; r++)
    for (let dj = -r; dj <= r; dj++)
      for (let di = -r; di <= r; di++) {
        if (Math.max(Math.abs(di), Math.abs(dj)) !== r) continue
        if (free(i + di, j + dj)) return [i + di, j + dj]
      }
  return null
}

/** The nearest point an agent can stand at, for targets that landed inside decor. */
export function nearestStandable(p: P): P {
  const c = nearestFree(...toCell(p))
  return c ? (isFree(p) ? p : toWorld(...c)) : p
}

/** A straight walk between two cells stays clear of decor. */
function clearLine(a: [number, number], b: [number, number]): boolean {
  const steps = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) * 3)
  for (let s = 1; s <= steps; s++) {
    const t = s / steps
    const x = a[0] + (b[0] - a[0]) * t
    const y = a[1] + (b[1] - a[1]) * t
    // sample the cells under the agent's body edges too
    for (const [dx, dy] of [[0, 0], [0.45, 0.45], [-0.45, 0.45], [0.45, -0.45], [-0.45, -0.45]]) {
      const ci = Math.round(x + dx)
      const cj = Math.round(y + dy)
      if (!free(ci, cj)) return false
    }
  }
  return true
}

const DIRS: [number, number, number][] = [
  [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
  [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2],
]

/**
 * A walk from `from` to `to` (world units) around decor: floor points to visit, ending at
 * `to` (or the nearest free spot to it). Null when there's no way through.
 */
export function navPath(from: P, to: P): P[] | null {
  const goal = nearestFree(...toCell(to))
  if (!goal || !inside(...toCell(from))) return null
  const target = goal[0] === toCell(to)[0] && goal[1] === toCell(to)[1] ? to : toWorld(...goal)
  if (!free(...toCell(from))) {
    // a brick was placed where the agent stands: step out to the nearest free spot first
    const out = nearestFree(...toCell(from))
    if (!out) return null
    const rest = navPath(toWorld(...out), target)
    return rest && [toWorld(...out), ...rest]
  }
  const start = toCell(from)
  if (clearLine(start, goal)) return [target]

  const s = idx(...start)
  const g = idx(...goal)
  const cost = new Float32Array(N * N).fill(Infinity)
  const came = new Int32Array(N * N).fill(-1)
  const closed = new Uint8Array(N * N)
  const h = (k: number) => {
    const dx = Math.abs((k % N) - goal[0])
    const dz = Math.abs(Math.floor(k / N) - goal[1])
    return Math.max(dx, dz) + (Math.SQRT2 - 1) * Math.min(dx, dz)
  }
  // a small binary heap keyed by f
  const heap: [number, number][] = []
  const push = (f: number, k: number) => {
    heap.push([f, k])
    for (let c = heap.length - 1; c > 0; ) {
      const p = (c - 1) >> 1
      if (heap[p][0] <= heap[c][0]) break
      ;[heap[p], heap[c]] = [heap[c], heap[p]]
      c = p
    }
  }
  const pop = (): number => {
    const top = heap[0][1]
    const last = heap.pop()!
    if (heap.length) {
      heap[0] = last
      for (let c = 0; ; ) {
        const l = 2 * c + 1
        const r = l + 1
        let m = c
        if (l < heap.length && heap[l][0] < heap[m][0]) m = l
        if (r < heap.length && heap[r][0] < heap[m][0]) m = r
        if (m === c) break
        ;[heap[m], heap[c]] = [heap[c], heap[m]]
        c = m
      }
    }
    return top
  }
  cost[s] = 0
  push(h(s), s)
  while (heap.length) {
    const k = pop()
    if (k === g) break
    if (closed[k]) continue
    closed[k] = 1
    const ki = k % N
    const kj = Math.floor(k / N)
    for (const [di, dj, c] of DIRS) {
      const ni = ki + di
      const nj = kj + dj
      if (!free(ni, nj)) continue
      // no squeezing diagonally between two blocked cells
      if (di && dj && (!free(ki + di, kj) || !free(ki, kj + dj))) continue
      const nk = idx(ni, nj)
      const nc = cost[k] + c
      if (nc < cost[nk]) {
        cost[nk] = nc
        came[nk] = k
        push(nc + h(nk), nk)
      }
    }
  }
  if (came[g] === -1 && g !== s) return null
  const cells: [number, number][] = []
  for (let k = g; k !== -1 && k !== s; k = came[k]) cells.unshift([k % N, Math.floor(k / N)])
  // straighten: from each point, jump to the furthest cell in a clear line
  const out: P[] = []
  let from_: [number, number] = start
  let at = 0
  while (at < cells.length) {
    let far = at
    for (let k = cells.length - 1; k > at; k--)
      if (clearLine(from_, cells[k])) {
        far = k
        break
      }
    from_ = cells[far]
    out.push(far === cells.length - 1 ? target : toWorld(...cells[far]))
    at = far + 1
  }
  return out.length ? out : [target]
}
