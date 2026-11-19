import { Vector3 } from 'three'
import { describe, expect, it } from 'vitest'

import { introPose, useIntro } from './introPath'

const end = { azimuth: Math.PI / 4, polar: 0.95, zoom: 40, target: new Vector3(-2, 0, -2) }

describe('the fly-in', () => {
  it('starts turned, higher, zoomed out and behind the floor', () => {
    const p = introPose(0, end)
    expect(p.azimuth).toBeLessThan(end.azimuth)
    expect(p.polar).toBeLessThan(end.polar)
    expect(p.zoom).toBeLessThan(end.zoom / 2)
    expect(p.target.x).toBeLessThan(end.target.x)
    expect(p.target.z).toBeLessThan(end.target.z)
  })

  it('ends exactly on the home framing, and stays there', () => {
    for (const t of [1, 1.5]) {
      const p = introPose(t, end)
      expect(p.azimuth).toBeCloseTo(end.azimuth)
      expect(p.polar).toBeCloseTo(end.polar)
      expect(p.zoom).toBeCloseTo(end.zoom)
      expect(p.target.distanceTo(end.target)).toBeCloseTo(0)
    }
  })

  it('never zooms out past what the controls allow', () => {
    expect(introPose(0, { ...end, zoom: 10 }).zoom).toBeGreaterThanOrEqual(8)
  })

  it('replays on demand', () => {
    const before = useIntro.getState().run
    useIntro.getState().play()
    expect(useIntro.getState().run).toBe(before + 1)
  })
})
