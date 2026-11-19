/** The fly-in's camera path and its replay trigger, without React or the 3D scene (intro.tsx). */
import { Vector3 } from 'three'
import { create } from 'zustand'

/** The tilt starts as near overhead as the controls allow. */
const TOP_POLAR = Math.PI / 4.5

export const useIntro = create<{ run: number; play: () => void }>((set) => ({
  run: 0,
  play: () => set((s) => ({ run: s.run + 1 })),
}))

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

/** Where the camera starts relative to where it ends: turned a sixth of the way round, from
 * higher up, zoomed well out, and looking at a point behind the floor. */
export function introPose(t: number, end: { azimuth: number; polar: number; zoom: number; target: Vector3 }) {
  const k = ease(Math.min(Math.max(t, 0), 1))
  return {
    azimuth: lerp(end.azimuth - 1.1, end.azimuth, k),
    polar: lerp(Math.min(TOP_POLAR, end.polar), end.polar, k),
    zoom: lerp(Math.max(end.zoom * 0.3, 8), end.zoom, k),
    target: new Vector3(end.target.x - 14, end.target.y, end.target.z - 14).lerp(end.target, k),
  }
}
