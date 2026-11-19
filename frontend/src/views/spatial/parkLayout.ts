/**
 * The park around the office: paths that carry the office's cross-shaped walkway out to the
 * edges, a loop path around it all, a pond, two fountain plazas, and the planting.
 *
 * Pure layout in world units (three.js x / z), seeded so it's the same on every load and the
 * scene and tests agree on where everything is. The camera looks in from +x / +z, so tall
 * trees keep out of the strip in front of the office; low planting is fine anywhere.
 */
import { STUD_W } from './bricks'
import { dist, type P } from './layout'

/** Half-size of the office floor: zones and walkway span ±20 studs. */
export const OFFICE = 20 * STUD_W
/** Half-width of the walkway arms, the same as the office's brick walkway. */
export const ARM = 4 * STUD_W
export const LOOP_R = 27
export const LOOP_W = 2.4
export const SPUR_W = 1.8
export const PLAZA_R = 3.2
/** Half-size of the painted ground; plain grass beyond. */
export const EXTENT = 70

const D = Math.SQRT1_2
const U: P = { x: D, z: -D } // screen-right from the default camera
const W: P = { x: D, z: D } // toward the camera

/** The pond sits in the front corner, its long axis across the screen. */
export const POND = { x: 21.5 * D, z: 21.5 * D, a: 6, b: 2.7 }
/** Fountain plazas in the left and right corners, each joined to the loop by a spur. */
export const FOUNTAINS: P[] = [
  { x: -20.5 * D, z: 20.5 * D },
  { x: 20.5 * D, z: -20.5 * D },
]
export const spurEnd = (f: P): P => {
  const k = LOOP_R / Math.hypot(f.x, f.z)
  return { x: f.x * k, z: f.z * k }
}

/** Deterministic random numbers in [0, 1). */
export function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const wobble = (t: number) => 1 + 0.06 * Math.sin(3 * t + 1) + 0.04 * Math.sin(5 * t + 2)

/** A point in the pond's own axes: u along its length, w across. */
export const pondPoint = (u: number, w: number): P => ({ x: POND.x + U.x * u + W.x * w, z: POND.z + U.z * u + W.z * w })

/** The shoreline, scaled by `k` (1 = the water's edge). */
export function pondOutline(k = 1, n = 64): P[] {
  return Array.from({ length: n }, (_, i) => {
    const t = (i / n) * Math.PI * 2
    const m = wobble(t) * k
    return pondPoint(POND.a * Math.cos(t) * m, POND.b * Math.sin(t) * m)
  })
}

/** How far out from the pond's middle a point is: under 0.9 is water, over 1.1 is dry land. */
export function pondRho(p: P): number {
  const dx = p.x - POND.x
  const dz = p.z - POND.z
  return Math.hypot((dx * U.x + dz * U.z) / POND.a, (dx * W.x + dz * W.z) / POND.b)
}

function segDist(p: P, a: P, b: P): number {
  const vx = b.x - a.x
  const vz = b.z - a.z
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * vx + (p.z - a.z) * vz) / (vx * vx + vz * vz)))
  return Math.hypot(p.x - a.x - t * vx, p.z - a.z - t * vz)
}

export const inOffice = (p: P, margin = 0) => Math.abs(p.x) < OFFICE + margin && Math.abs(p.z) < OFFICE + margin

/** On a path or plaza, or within `margin` of one. */
export function onPath(p: P, margin = 0): boolean {
  const ax = Math.abs(p.x)
  const az = Math.abs(p.z)
  if ((az < ARM + margin && ax > OFFICE - 1) || (ax < ARM + margin && az > OFFICE - 1)) return true
  if (Math.abs(Math.hypot(p.x, p.z) - LOOP_R) < LOOP_W / 2 + margin) return true
  return FOUNTAINS.some((f) => dist(p, f) < PLAZA_R + margin || segDist(p, f, spurEnd(f)) < SPUR_W / 2 + margin)
}

/** In the strip between the office and the default camera, where a tree would hide the floor. */
export function hidesOffice(p: P): boolean {
  const depth = (p.x + p.z) * D
  const across = (p.x - p.z) * D
  return depth > 10 && depth < 27 && Math.abs(across) < 19
}

export interface Tree {
  x: number
  z: number
  kind: 'round' | 'pine' | 'blossom'
  trunk: number
  size: number
  tone: number
  rot: number
}
/** Something small on the ground: a bush, flower or rock. */
export interface Dot {
  x: number
  z: number
  size: number
  color: string
}
export interface Rect {
  x: number
  z: number
  w: number
  d: number
}
export interface Bench {
  x: number
  z: number
  /** Turn about y; the seat faces local +z. */
  rot: number
}

export const FLOWER_COLORS = ['#ff7aa8', '#ffd84a', '#ffffff', '#b48cff', '#ff9a4a', '#ff5f6d', '#7ec8ff']
const BED_PAIRS: [string, string][] = [
  ['#ff7aa8', '#ffffff'],
  ['#ffd84a', '#ff9a4a'],
  ['#b48cff', '#ff7aa8'],
  ['#ff5f6d', '#ffd84a'],
  ['#7ec8ff', '#ffffff'],
]
const BUSH_COLORS = ['#3f8a45', '#4c9a4a', '#5aa851', '#367a43']
const ROCK_COLORS = ['#a7a29a', '#938f88', '#b8b3a9']

/** The four walkway arms: direction out of the office, and the side-to-side normal. */
const ARMS = [
  { d: { x: 1, z: 0 }, n: { x: 0, z: 1 } },
  { d: { x: -1, z: 0 }, n: { x: 0, z: 1 } },
  { d: { x: 0, z: 1 }, n: { x: 1, z: 0 } },
  { d: { x: 0, z: -1 }, n: { x: 1, z: 0 } },
]
const along = (arm: (typeof ARMS)[number], t: number, off: number): P => ({ x: arm.d.x * t + arm.n.x * off, z: arm.d.z * t + arm.n.z * off })

/** Flower beds line each arm between the office and the loop, broken by lamp posts. */
const BEDS: [number, number][] = [
  [OFFICE + 1.2, OFFICE + 4.4],
  [OFFICE + 5.4, OFFICE + 8.6],
  [OFFICE + 9.6, LOOP_R - LOOP_W / 2 - 0.8],
]
const BED_IN = ARM + 0.45
const BED_OUT = ARM + 1.35

function layoutPark() {
  const r = rng(20261118)
  const between = (lo: number, hi: number) => lo + r() * (hi - lo)
  const pick = <T,>(xs: readonly T[]) => xs[Math.floor(r() * xs.length)]

  // Flower beds and lamps along the arms
  const beds: Rect[] = []
  const flowers: Dot[] = []
  const lamps: P[] = []
  ARMS.forEach((arm, ai) => {
    for (const side of [-1, 1]) {
      BEDS.forEach(([t0, t1], bi) => {
        const a = along(arm, t0, side * BED_IN)
        const b = along(arm, t1, side * BED_OUT)
        beds.push({ x: (a.x + b.x) / 2, z: (a.z + b.z) / 2, w: Math.abs(b.x - a.x), d: Math.abs(b.z - a.z) })
        const [c1, c2] = BED_PAIRS[(ai * 2 + bi + (side > 0 ? 1 : 0)) % BED_PAIRS.length]
        for (let t = t0 + 0.2; t < t1 - 0.1; t += 0.27)
          for (const row of [0.68, 1.1]) {
            const p = along(arm, t + between(-0.05, 0.05), side * (ARM + row + between(-0.06, 0.06)))
            flowers.push({ ...p, size: between(0.09, 0.13), color: r() < 0.6 ? c1 : c2 })
          }
      })
    }
    // between the beds, then out past the loop
    ;[OFFICE + 4.9, OFFICE + 9.1, 31, 38, 46].forEach((t, i) => lamps.push(along(arm, t, (i % 2 ? 1 : -1) * (ARM + 0.4))))
  })

  // Low hedges frame the office, open where the walkway leaves it
  const hedges: Rect[] = []
  const h = OFFICE + 0.45
  const span = (lo: number, hi: number) => ({ mid: (lo + hi) / 2, len: hi - lo })
  for (const s of [-1, 1])
    for (const half of [-1, 1]) {
      const { mid, len } = span(ARM + 0.5, OFFICE + 0.7)
      hedges.push({ x: half * mid, z: s * h, w: len, d: 0.5 })
      hedges.push({ x: s * h, z: half * mid, w: 0.5, d: len })
    }

  // Fountain plazas: a ring of flowers, benches either side of the spur
  const benches: Bench[] = []
  for (const f of FOUNTAINS) {
    const out = Math.atan2(f.z, f.x)
    for (let a = 0; a < Math.PI * 2; a += 0.11) {
      const diff = Math.abs(Math.atan2(Math.sin(a - out), Math.cos(a - out)))
      if (diff < 0.5) continue
      for (const rr of [PLAZA_R + 0.45, PLAZA_R + 0.85])
        flowers.push({ x: f.x + Math.cos(a) * rr, z: f.z + Math.sin(a) * rr, size: between(0.09, 0.13), color: pick(FLOWER_COLORS) })
    }
    for (const s of [-1, 1]) {
      const a = out + (s * Math.PI) / 2
      const rr = PLAZA_R - 0.55
      // the seat faces the fountain: local +z points back toward the center
      benches.push({ x: f.x + Math.cos(a) * rr, z: f.z + Math.sin(a) * rr, rot: Math.atan2(-Math.cos(a), -Math.sin(a)) })
    }
  }

  // Trees: everywhere but the paths, pond and the view of the office; a grove out back
  const trees: Tree[] = []
  const treeOk = (p: P) =>
    !inOffice(p, 2.2) && !onPath(p, 1.4) && pondRho(p) > 1.6 && !hidesOffice(p) && Math.max(Math.abs(p.x), Math.abs(p.z)) < EXTENT - 10 && trees.every((t) => dist(t, p) > 2.6)
  const gauss = () => (r() + r() + r() - 1.5) * 2
  for (let i = 0; i < 5000 && trees.length < 230; i++) {
    const grove = i < 500
    const p = grove ? { x: -21 + gauss() * 4, z: -21 + gauss() * 4 } : { x: between(-58, 58), z: between(-58, 58) }
    if (!treeOk(p)) continue
    const roll = r()
    const kind: Tree['kind'] = roll < 0.3 ? 'pine' : roll < 0.4 ? 'blossom' : 'round'
    trees.push({ ...p, kind, trunk: between(0.7, 1.1), size: between(0.95, 1.5), tone: r(), rot: r() * Math.PI * 2 })
  }

  // Bushes, wildflowers and rocks fill in the grass
  const bushes: Dot[] = []
  for (let i = 0; i < 4000 && bushes.length < 260; i++) {
    const p = { x: between(-55, 55), z: between(-55, 55) }
    if (inOffice(p, 1.2) || onPath(p, 0.8) || pondRho(p) < 1.35) continue
    if (bushes.some((b) => dist(b, p) < 1.1) || trees.some((t) => dist(t, p) < 1.3)) continue
    bushes.push({ ...p, size: between(0.35, 0.7), color: pick(BUSH_COLORS) })
  }
  for (let i = 0; i < 3000 && flowers.length < 1400; i++) {
    const p = { x: between(-45, 45), z: between(-45, 45) }
    if (inOffice(p, 0.6) || onPath(p, 0.3) || pondRho(p) < 1.25) continue
    flowers.push({ ...p, size: between(0.06, 0.09), color: pick(FLOWER_COLORS) })
  }
  const rocks: Dot[] = []
  pondOutline(1.13, 26).forEach((p) => {
    if (r() < 0.6) rocks.push({ x: p.x + between(-0.15, 0.15), z: p.z + between(-0.15, 0.15), size: between(0.18, 0.4), color: pick(ROCK_COLORS) })
  })
  for (let i = 0; i < 200 && rocks.length < 40; i++) {
    const p = { x: between(-50, 50), z: between(-50, 50) }
    if (!inOffice(p, 1) && !onPath(p, 0.5) && pondRho(p) > 1.4) rocks.push({ ...p, size: between(0.2, 0.55), color: pick(ROCK_COLORS) })
  }

  // Reeds at both ends of the pond, lily pads on it
  const reeds: Dot[] = []
  for (const end of [0, Math.PI])
    for (let i = 0; i < 18; i++) {
      const t = end + between(-0.55, 0.55)
      const m = wobble(t) * between(0.92, 1.04)
      reeds.push({ ...pondPoint(POND.a * Math.cos(t) * m, POND.b * Math.sin(t) * m), size: between(0.5, 0.95), color: r() < 0.5 ? '#5b8f3a' : '#6e9e45' })
    }
  const lilies: (Dot & { bloom: boolean })[] = []
  for (let i = 0; i < 300 && lilies.length < 13; i++) {
    const p = pondPoint(between(-POND.a, POND.a) * 0.8, between(-POND.b, POND.b) * 0.8)
    if (pondRho(p) < 0.72 && lilies.every((l) => dist(l, p) > 0.8)) lilies.push({ ...p, size: between(0.22, 0.36), color: '#4f9a3f', bloom: r() < 0.4 })
  }

  return { beds, flowers, lamps, hedges, benches, trees, bushes, rocks, reeds, lilies }
}

export const PARK = layoutPark()
