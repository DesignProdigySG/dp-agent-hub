/**
 * The cinematic fly-in: when the office opens (or the replay button is pressed) the camera
 * glides in from behind the floor, zoomed out, to the usual framing, then turns slowly around
 * the office until someone takes the controls.
 */
import type { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef, type ComponentRef, type RefObject } from 'react'
import { Spherical, Vector3, type OrthographicCamera } from 'three'

import { Button, Icon } from '../../components/ui'
import { useHub } from '../../store/hub'
import { introPose, useIntro } from './introPath'

/** Seconds the fly-in takes. */
export const INTRO_S = 5
/** The longest step one frame may take (a 30 fps frame). */
const MAX_STEP_S = 1 / 30
/** Slow turn afterwards (OrbitControls units: 2 = one turn every 30 s). */
const TURN_SPEED = 0.35
/** The office's home framing: the camera's offset from the target (see SpatialView). */
const HOME = new Spherical().setFromVector3(new Vector3(24, 24, 24))

type Controls = ComponentRef<typeof OrbitControls>

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

export function CinematicIntro({ controls, fitZoom, target }: {
  controls: RefObject<Controls | null>
  fitZoom: (width: number, height: number) => number
  target: [number, number, number]
}) {
  const camera = useThree((s) => s.camera) as OrthographicCamera
  const size = useThree((s) => s.size)
  const run = useIntro((s) => s.run)
  const view = useHub((s) => s.view)
  const anim = useRef<{ elapsed: number; end: Parameters<typeof introPose>[1]; radius: number } | null>(null)
  // A fly-in waiting to start: whenever the Spatial tab opens, and on every replay. It starts
  // on the first frame the controls exist, since they attach after this component's effects.
  const pending = useRef(true)
  useEffect(() => {
    if (view === 'spatial') pending.current = true
  }, [run, view])

  useFrame((_, delta) => {
    const c = controls.current
    if (!c) return
    if (pending.current) {
      pending.current = false
      const end = { azimuth: HOME.theta, polar: HOME.phi, zoom: fitZoom(size.width, size.height), target: new Vector3(...target) }
      anim.current = { elapsed: 0, end, radius: HOME.radius }
      c.autoRotate = false
      c.enabled = false
    }
    const a = anim.current
    if (!a) return
    // Frame by frame, each step capped: a stall while the office loads pauses the fly-in
    // rather than skipping it
    a.elapsed += Math.min(delta, MAX_STEP_S)
    const t = reducedMotion() ? 1 : a.elapsed / INTRO_S
    const pose = introPose(t, a.end)
    c.target.copy(pose.target)
    camera.position.copy(pose.target).add(new Vector3().setFromSpherical(new Spherical(a.radius, pose.polar, pose.azimuth)))
    camera.zoom = pose.zoom
    camera.updateProjectionMatrix()
    camera.lookAt(pose.target)
    if (t >= 1) {
      anim.current = null
      c.enabled = true
      c.autoRotate = !reducedMotion()
      c.autoRotateSpeed = TURN_SPEED
    }
    c.update()
  })
  return null
}

/** Taking the controls (a drag or a scroll) stops the slow turn. */
export const stopTurning = (c: Controls | null) => {
  if (c) c.autoRotate = false
}

/** Replays the fly-in. */
export function ReplayIntro() {
  return (
    <Button variant="tonal" onClick={useIntro.getState().play} title="Replay the fly-in">
      <Icon name="play_arrow" />
    </Button>
  )
}
