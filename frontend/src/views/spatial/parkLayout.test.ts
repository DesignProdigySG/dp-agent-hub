import { describe, expect, it } from 'vitest'

import { floorAt } from './placement'
import { STUD_W } from './bricks'
import { ARM, FOUNTAINS, hidesOffice, inOffice, LOOP_R, LOOP_W, OFFICE, onPath, PARK, pondOutline, pondRho } from './parkLayout'

describe('park', () => {
  it('starts where the office floor ends, and carries the walkway out', () => {
    expect(floorAt(OFFICE / STUD_W - 0.5, 0)).toBe(1)
    expect(floorAt(OFFICE / STUD_W + 0.5, 6)).toBe(0)
    expect(onPath({ x: OFFICE + 5, z: ARM - 0.1 })).toBe(true) // an arm, the walkway's width
    expect(onPath({ x: OFFICE + 5, z: ARM + 0.1 })).toBe(false)
    expect(onPath({ x: 0, z: -LOOP_R })).toBe(true)
    expect(FOUNTAINS.every((f) => onPath(f))).toBe(true)
  })

  it('keeps the pond clear of the office and the paths', () => {
    for (const p of pondOutline(1.2)) {
      expect(inOffice(p, 1)).toBe(false)
      expect(onPath(p)).toBe(false)
    }
    expect(Math.max(...pondOutline(1.2).map((p) => Math.hypot(p.x, p.z)))).toBeLessThan(LOOP_R - LOOP_W / 2)
  })

  it('plants trees on open grass, never in front of the office', () => {
    expect(PARK.trees.length).toBeGreaterThan(100)
    for (const t of PARK.trees) {
      expect(inOffice(t, 1)).toBe(false)
      expect(onPath(t, 1)).toBe(false)
      expect(pondRho(t)).toBeGreaterThan(1.3)
      expect(hidesOffice(t)).toBe(false)
    }
  })

  it('keeps flowers, bushes, lamps and rocks off the paths and out of the water', () => {
    for (const p of [...PARK.flowers, ...PARK.bushes, ...PARK.lamps, ...PARK.rocks]) {
      expect(onPath(p)).toBe(false)
      expect(inOffice(p)).toBe(false)
      expect(pondRho(p)).toBeGreaterThan(1)
    }
  })
})
