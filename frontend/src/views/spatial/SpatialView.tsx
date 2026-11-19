import { OrbitControls, OrthographicCamera } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Suspense, useEffect, useRef, type ComponentRef } from 'react'
import type { OrthographicCamera as OrthoCam } from 'three'

import { Button, Icon } from '../../components/ui'
import { useHub } from '../../store/hub'
import { AgentAvatar, AgentLabel } from './AgentAvatar'
import { preloadCharacters } from './AgentModel'
import { Build, preloadBricks, type BrickSpec } from './bricks'
import { Decor } from './Decor'
import { DEFAULT_DECOR } from './placement'
import { EditPanel } from './EditPanel'
import { FloorLogo } from './FloorLogo'
import { CinematicIntro, ReplayIntro, stopTurning } from './intro'
import { LabelProjector } from './labels'
import { Park } from './Park'
import { replanAll, talkers, tickTalks } from './motion'
import { setObstacles } from './navgrid'
import { ZONES } from './layout'
import { useScene } from './sceneStore'
import { useSpeech } from './speech'
import { useSceneColors } from './theme'
import { ZoneCard, ZonePlatform } from './ZonePlatform'
import { ZoneSigns } from './ZoneSigns'

/** Smooth tiles forming the cross-shaped walkway between the zones (stud space). The 8×8
 * crossing in the middle is left open for the Marketo floor tile. */
const WALKWAY: BrickSpec[] = [-3, -1, 1, 3].flatMap((row) => [
  ...[-16, -8, 8, 16].map((x): BrickSpec => ['none-hq-plate-2x8', 'steel', x, 0, row]),
  ...[-16, -8, 8, 16].map((z): BrickSpec => ['none-hq-plate-2x8', 'steel', row, 0, z, Math.PI / 2]),
])

preloadBricks([...WALKWAY.map((b) => b[0]), 'round-hq-plate-4x8', ...DEFAULT_DECOR.map((p) => p.piece)])
preloadCharacters()

/** Pixels at the top of the panel taken by the zone KPI strip. */
const HUD_PX = 120
/** Looking slightly past the center moves the floor down, clear of the KPI strip. */
const TARGET: [number, number, number] = [-2, 0, -2]

/** The zoom that keeps the whole 4-zone floor in frame. */
const fitZoom = (width: number, height: number) => Math.max(Math.min(width / 40, (height - HUD_PX) / 25), 8)

/** Keep the whole floor in frame as the panel resizes. */
function FitZoom() {
  const { size, camera } = useThree()
  useEffect(() => {
    const cam = camera as OrthoCam
    cam.zoom = fitZoom(size.width, size.height)
    cam.updateProjectionMatrix()
  }, [size, camera])
  return null
}

/** Keep the walkable grid in step with the decor. */
function Navigation() {
  const pieces = useScene((s) => s.pieces)
  useEffect(() => {
    setObstacles(pieces)
    replanAll()
  }, [pieces])
  return null
}

/** Hand-offs: the two agents meet, say their lines (speech bubbles), and part. */
function Conversations() {
  useFrame(({ clock }) => useSpeech.getState().setLines(tickTalks(clock.elapsedTime), talkers()))
  return null
}

function Scene() {
  const agents = useHub((s) => s.agents).filter((a) => a.enabled)
  const colors = useSceneColors()
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null)

  return (
    <>
      <color attach="background" args={[colors.bg]} />
      <OrthographicCamera makeDefault position={[TARGET[0] + 24, 24, TARGET[2] + 24]} near={-100} far={200} />
      <FitZoom />
      <Navigation />
      <Conversations />
      <LabelProjector />
      <OrbitControls
        ref={controls}
        onStart={() => stopTurning(controls.current)}
        target={TARGET}
        enableRotate
        minPolarAngle={Math.PI / 4.5}
        maxPolarAngle={Math.PI / 3.2}
        minZoom={8}
        maxZoom={90}
        enableDamping
      />
      <CinematicIntro controls={controls} fitZoom={fitZoom} target={TARGET} />
      <hemisphereLight args={['#ffffff', colors.floor, colors.theme === 'dark' ? 0.9 : 1.3]} />
      <directionalLight
        position={[12, 22, 8]}
        intensity={colors.theme === 'dark' ? 1.4 : 1.8}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-26}
        shadow-camera-right={26}
        shadow-camera-top={26}
        shadow-camera-bottom={-26}
        shadow-bias={-0.0005}
      />
      <Park />
      <Suspense fallback={null}>
        <Build parts={WALKWAY} />
        {ZONES.map((z) => (
          <ZonePlatform key={z} zone={z} />
        ))}
        <Decor />
        <FloorLogo />
        <ZoneSigns />
        {agents.map((a) => (
          <AgentAvatar key={a.id} profile={a} errorColor={colors.error} />
        ))}
      </Suspense>
    </>
  )
}

/** Zone KPIs, and agent name tags positioned by LabelProjector. */
/** "Edit space", only once the saved layout has loaded, plus a draft-restore offer. */
function EditControls() {
  const status = useScene((s) => s.status)
  const draft = useScene((s) => s.draft)
  const { startEditing, restoreDraft, discardDraft } = useScene.getState()
  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-30 flex max-w-xs flex-col items-end gap-2">
      <Button variant="tonal" disabled={status !== 'ready'} onClick={startEditing} title={status === 'ready' ? undefined : 'Waiting for the saved layout to load'}>
        <Icon name={status === 'ready' ? 'construction' : 'hourglass_top'} /> {status === 'ready' ? 'Edit space' : 'Loading layout…'}
      </Button>
      {status === 'error' && (
        <p className="rounded-xl bg-error-container px-3 py-2 text-xs text-error">
          Couldn't load the saved layout; retrying. Editing stays off until it loads, so nothing can be saved over it.
        </p>
      )}
      {status === 'ready' && draft && (
        <div className="rounded-xl bg-surface/95 px-3 py-2 text-xs shadow">
          <p>
            Unsaved edits from {new Date(draft.at).toLocaleString()} ({draft.pieces.length} pieces).
          </p>
          <div className="mt-1 flex justify-end gap-1">
            <Button variant="text" className="!h-7 !px-2" onClick={discardDraft}>Discard</Button>
            <Button variant="tonal" className="!h-7 !px-2" onClick={restoreDraft}>Keep editing</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function Labels() {
  const agents = useHub((s) => s.agents).filter((a) => a.enabled)
  const editing = useScene((s) => s.editing)
  const isAdmin = useHub((s) => s.auth.authenticated)
  return (
    <div className="pointer-events-none absolute inset-0">
      {editing ? (
        <EditPanel />
      ) : (
        <div className="absolute inset-x-3 top-3 z-30 flex flex-wrap gap-2 pr-28">
          {ZONES.map((z) => (
            <ZoneCard key={z} zone={z} />
          ))}
        </div>
      )}
      {!editing && (
        <div className="pointer-events-auto absolute bottom-3 right-3 z-30 flex items-center gap-2">
          <ReplayIntro />
        </div>
      )}
      {isAdmin && !editing && <EditControls />}
      {agents.map((a) => (
        <AgentLabel key={a.id} profile={a} />
      ))}
    </div>
  )
}

export default function SpatialView() {
  useEffect(() => {
    useScene.getState().load()
  }, [])
  return (
    <div className="relative h-full w-full overflow-hidden rounded-3xl bg-surface-dim">
      <Canvas shadows dpr={[1, 2]}>
        <Scene />
      </Canvas>
      <Labels />
      <div className="pointer-events-none absolute bottom-3 left-4 text-xs text-on-surface-variant">Drag to orbit · scroll to zoom · click an agent for details</div>
    </div>
  )
}
