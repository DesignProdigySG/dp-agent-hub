/**
 * Renders the decor layout, and in edit mode the pointer surface and ghost piece.
 *
 * In edit mode a click on a placed piece picks it up; with a piece in hand, the ghost
 * follows the pointer (snapped to the stud grid, resting on whatever is below it) and a
 * click drops it. Drags (orbiting the camera) never place or pick up.
 */
import type { ThreeEvent } from '@react-three/fiber'
import { useMemo, useState } from 'react'
import { Plane, Vector3, type MeshStandardMaterial } from 'three'

import { BRICK_SCALE, isLab, LabBuild, materialFor, PLATE, STUD, STUD_W, usePiece, type BrickColor, type BrickPiece, type Piece } from './bricks'
import { footprint, restingLayer, snap, type Placed } from './placement'
import { useScene } from './sceneStore'

const CLICK_PX = 5 // pointer travel that still counts as a click, not an orbit drag

function PlacedPiece({ p, index, editing }: { p: Placed; index: number; editing: boolean }) {
  const handlers = editing
    ? {
        onClick: (e: ThreeEvent<MouseEvent>) => {
          if (e.delta > CLICK_PX || useScene.getState().active) return // let the surface drop
          e.stopPropagation()
          useScene.getState().pickUp(index)
        },
        onPointerOver: () => (document.body.style.cursor = 'grab'),
        onPointerOut: () => (document.body.style.cursor = ''),
      }
    : {}
  const position: [number, number, number] = [p.x * STUD, p.y * PLATE, p.z * STUD]
  if (isLab(p.piece))
    return (
      <group position={position} rotation-y={(p.rot * Math.PI) / 2}>
        <LabBuild piece={p.piece} {...handlers} />
      </group>
    )
  return <KitPiece p={p as Placed & { piece: BrickPiece }} position={position} {...handlers} />
}

function KitPiece({ p, position, ...handlers }: { p: Placed & { piece: BrickPiece }; position: [number, number, number]; onClick?: (e: ThreeEvent<MouseEvent>) => void; onPointerOver?: () => void; onPointerOut?: () => void }) {
  const { geometry, base } = usePiece(p.piece)
  return <mesh geometry={geometry} material={materialFor(base, p.color)} position={position} rotation-y={(p.rot * Math.PI) / 2} castShadow receiveShadow {...handlers} />
}

const ghostMaterials = new Map<string, MeshStandardMaterial>()

function Ghost({ piece, color, rot, at }: { piece: Piece; color: BrickColor; rot: number; at: [number, number, number] }) {
  if (isLab(piece))
    return (
      <group position={[at[0] * STUD, at[1] * PLATE, at[2] * STUD]} rotation-y={(rot * Math.PI) / 2}>
        <LabBuild piece={piece} ghost />
      </group>
    )
  return <KitGhost piece={piece} color={color} rot={rot} at={at} />
}

function KitGhost({ piece, color, rot, at }: { piece: BrickPiece; color: BrickColor; rot: number; at: [number, number, number] }) {
  const { geometry, base } = usePiece(piece)
  const material = useMemo(() => {
    let m = ghostMaterials.get(color)
    if (!m) {
      m = materialFor(base, color).clone()
      m.transparent = true
      m.opacity = 0.6
      m.depthWrite = false
      ghostMaterials.set(color, m)
    }
    return m
  }, [base, color])
  return <mesh geometry={geometry} material={material} position={[at[0] * STUD, at[1] * PLATE, at[2] * STUD]} rotation-y={(rot * Math.PI) / 2} renderOrder={10} />
}

const plane = new Plane(new Vector3(0, 1, 0), 0)
const hit = new Vector3()

/** Where the active piece would land for a pointer ray: [x, layer, z] in studs. */
function placement(e: ThreeEvent<PointerEvent | MouseEvent>, p: Pick<Placed, 'piece' | 'rot'>, others: Placed[]): [number, number, number] | null {
  const [w, d] = footprint(p)
  let layer = 0
  let at: [number, number, number] | null = null
  // Aim at the height the piece will rest at: refine twice so stacks track the cursor.
  for (let i = 0; i < 3; i++) {
    plane.constant = -layer * PLATE * BRICK_SCALE
    if (!e.ray.intersectPlane(plane, hit)) return at
    const x = snap(hit.x / STUD_W, w)
    const z = snap(hit.z / STUD_W, d)
    const y = restingLayer(p, x, z, others)
    at = [x, y, z]
    if (y === layer) break
    layer = y
  }
  return at
}

/** Invisible floor that tracks the pointer and drops the active piece (edit mode only). */
function EditSurface() {
  const active = useScene((s) => s.active)
  const pieces = useScene((s) => s.pieces)
  const [at, setAt] = useState<[number, number, number] | null>(null)

  const track = (e: ThreeEvent<PointerEvent>) => {
    if (active) setAt(placement(e, active, pieces))
  }
  const click = (e: ThreeEvent<MouseEvent>) => {
    if (e.delta > CLICK_PX || !active) return
    const spot = placement(e, active, pieces)
    if (spot) useScene.getState().drop(...spot)
  }

  return (
    <>
      <mesh rotation-x={-Math.PI / 2} position-y={0.001} onPointerMove={track} onClick={click} onPointerLeave={() => setAt(null)}>
        <planeGeometry args={[120, 120]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      {active && at && (
        <group scale={BRICK_SCALE}>
          <Ghost piece={active.piece} color={active.color} rot={active.rot} at={at} />
        </group>
      )}
    </>
  )
}

export function Decor() {
  const pieces = useScene((s) => s.pieces)
  const editing = useScene((s) => s.editing)
  return (
    <>
      <group scale={BRICK_SCALE}>
        {pieces.map((p, i) => (
          <PlacedPiece key={`${i}:${p.piece}:${p.x}:${p.y}:${p.z}`} p={p} index={i} editing={editing} />
        ))}
      </group>
      {editing && <EditSurface />}
    </>
  )
}
