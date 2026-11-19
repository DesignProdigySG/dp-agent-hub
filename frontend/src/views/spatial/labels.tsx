/**
 * HTML labels pinned to points in the 3D scene.
 *
 * Labels are ordinary React elements in an overlay above the canvas (no extra React roots or
 * portals, so they mount and unmount with the view like any other DOM). Each registers an
 * anchor; `LabelProjector`, inside the canvas, moves them to their projected screen position
 * every frame without re-rendering React.
 */
import { useFrame, useThree } from '@react-three/fiber'
import { useCallback } from 'react'
import { Vector3 } from 'three'

type Anchor = () => { x: number; y: number; z: number } | null

const labels = new Map<string, { el: HTMLElement; anchor: Anchor }>()

/** Ref callback that pins an element to `anchor` (world coordinates, or null to hide). */
export function useLabel(key: string, anchor: Anchor) {
  return useCallback(
    (el: HTMLElement | null) => {
      if (el) labels.set(key, { el, anchor })
      else labels.delete(key)
    },
    [key, anchor],
  )
}

const v = new Vector3()
const MARGIN = 8

export function LabelProjector() {
  const { camera, size } = useThree()
  useFrame(() => {
    for (const { el, anchor } of labels.values()) {
      const p = anchor()
      if (!p) {
        el.style.visibility = 'hidden'
        continue
      }
      v.set(p.x, p.y, p.z).project(camera)
      // keep the whole label inside the panel (it is centered on x and sits above y)
      const halfW = el.offsetWidth / 2 + MARGIN
      const x = Math.min(Math.max(((v.x + 1) / 2) * size.width, halfW), size.width - halfW)
      const y = Math.min(Math.max(((1 - v.y) / 2) * size.height, el.offsetHeight + MARGIN), size.height - MARGIN)
      el.style.visibility = v.z < 1 ? 'visible' : 'hidden'
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`
    }
  })
  return null
}
