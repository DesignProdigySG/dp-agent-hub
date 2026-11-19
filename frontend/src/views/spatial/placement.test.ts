import { describe, expect, it } from 'vitest'

import { DEFAULT_DECOR, floorAt, footprint, restingLayer, sanitize, snap, zoneStuds, type Placed } from './placement'

const brick = (x: number, z: number, y = 1): Placed => ({ piece: 'round-hq-brick-2x4', color: 'red', x, y, z, rot: 0 })

describe('placement', () => {
  it('rotates footprints and snaps centers to the stud grid', () => {
    expect(footprint({ piece: 'round-hq-brick-2x4', rot: 0 })).toEqual([4, 2])
    expect(footprint({ piece: 'round-hq-brick-2x4', rot: 1 })).toEqual([2, 4])
    expect(footprint({ piece: 'lab-desk-setup', rot: 0 })).toEqual([5, 3]) // a Brick Lab build, at LAB_SCALE
    expect(footprint({ piece: 'lab-desk-setup', rot: 3 })).toEqual([3, 5])
    expect(snap(3.2, 4)).toBe(3) // even width: center on a grid line
    expect(snap(3.2, 1)).toBe(3.5) // odd width: center on a stud
  })

  it('rests pieces on the floor, baseplates and each other', () => {
    expect(floorAt(30, 30)).toBe(0) // open floor
    expect(floorAt(12, 12)).toBe(1) // a zone baseplate
    expect(floorAt(0, 0)).toBe(1) // the walkway
    expect(restingLayer({ piece: 'round-hq-brick-2x4', rot: 0 }, 12, 12, [])).toBe(1)
    expect(restingLayer({ piece: 'round-hq-brick-2x4', rot: 0 }, 12, 12, [brick(12, 12)])).toBe(4) // on the brick
    expect(restingLayer({ piece: 'round-hq-brick-2x4', rot: 0 }, 16, 12, [brick(12, 12)])).toBe(1) // edges touch
    expect(restingLayer({ piece: 'round-hq-brick-2x4', rot: 0 }, 15, 12, [brick(12, 12)])).toBe(4) // overlaps by one
  })

  it('puts baseplates, decor and the walkway on one stud grid', () => {
    expect(zoneStuds('break_room')).toEqual({ x: -12, z: 12 }) // baseplate edges at -20..-4, 4..20
    const onGrid = (v: number, size: number) => Number.isInteger(v - size / 2)
    expect(DEFAULT_DECOR.every((p) => onGrid(p.x, footprint(p)[0]) && onGrid(p.z, footprint(p)[1]))).toBe(true)
    expect(floorAt(4.5, 4.5)).toBe(1) // zone starts right where the walkway ends
    expect(floorAt(3.5, 4.5)).toBe(1)
  })

  it('has a default decor and drops unknown pieces from the server', () => {
    expect(DEFAULT_DECOR.length).toBeGreaterThan(20)
    expect(DEFAULT_DECOR.every((p) => p.y >= 1)).toBe(true)
    // nothing in the default office overlaps anything else
    const overlap = (a: Placed, b: Placed) => {
      const [aw, ad] = footprint(a)
      const [bw, bd] = footprint(b)
      return a.y === b.y && Math.abs(a.x - b.x) < (aw + bw) / 2 && Math.abs(a.z - b.z) < (ad + bd) / 2
    }
    expect(DEFAULT_DECOR.filter((a, i) => DEFAULT_DECOR.some((b, j) => j > i && overlap(a, b)))).toEqual([])
    // and every piece is on a zone baseplate
    expect(DEFAULT_DECOR.every((p) => floorAt(p.x, p.z) === 1 && Math.abs(p.x) >= 4 && Math.abs(p.z) >= 4)).toBe(true)
    expect(sanitize([{ piece: 'round-hq-brick-1x1', color: 'red', x: 0, y: 1, z: 0.2, rot: 0 }])[0]).toMatchObject({ x: 0.5, z: 0.5 })
    expect(sanitize([{ piece: 'round-hq-brick-2x2', color: 'red', x: 0, y: 1, z: 0, rot: 5 }, { piece: 'mystery', color: 'red', x: 0, y: 0, z: 0, rot: 0 }])).toEqual([
      { piece: 'round-hq-brick-2x2', color: 'red', x: 0, y: 1, z: 0, rot: 1 },
    ])
  })
})
