/**
 * Kenney Brick Kit (CC0) pieces and Brick Lab builds (see lab.ts), placed on a stud grid.
 *
 * Every piece shares one palette texture; a piece's color is the palette column its UVs
 * land on, so recoloring is a texture offset (one cached material per color). Positions are
 * in studs (x / z) and plate layers (y; a brick is 3 layers), scaled so a 16-stud plate
 * spans a zone.
 */
import { useGLTF } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { useMemo } from 'react'
import { Mesh, MeshStandardMaterial, type BufferGeometry, type Material, type Texture } from 'three'

import { LAB_MODELS, LAB_SCALE, type LabModel } from './lab'

const BASE = '/assets/kenney/brick-kit'

/** Footprint [x studs, z studs] and height in plate layers, read from each model's bounds. */
const BRICK_INFO = {
  'round-hq-brick-1x1': [1, 1, 3],
  'round-hq-brick-1x1-round': [1, 1, 3],
  'round-hq-brick-1x2': [2, 1, 3],
  'round-hq-brick-1x4': [4, 1, 3],
  'round-hq-brick-1x6': [6, 1, 3],
  'round-hq-brick-1x8': [8, 1, 3],
  'round-hq-brick-2x2': [2, 2, 3],
  'round-hq-brick-2x4': [4, 2, 3],
  'round-hq-brick-2x6': [6, 2, 3],
  'round-hq-brick-2x8': [8, 2, 3],
  'round-hq-brick-corner': [2, 2, 3],
  'round-hq-brick-slope-1x2': [2, 1, 3],
  'round-hq-brick-slope-2x2': [2, 2, 3],
  'round-hq-brick-slope-2x3': [2, 3, 3],
  'round-hq-brick-slope-2x4': [2, 4, 3],
  'round-hq-brick-slope-3x1': [3, 1, 3],
  'round-hq-brick-slope-3x2': [3, 2, 3],
  'round-hq-brick-slope-corner-inside-2x2': [2, 2, 3],
  'round-hq-brick-slope-corner-inside-inverted-2x2': [2, 2, 3],
  'round-hq-brick-slope-corner-outside-2x2': [2, 2, 3],
  'round-hq-brick-slope-corner-outside-inverted-2x2': [2, 2, 3],
  'round-hq-brick-slope-inverted-1x2': [2, 1, 3],
  'round-hq-brick-slope-inverted-2x2': [2, 2, 3],
  'round-hq-plate-1x1': [1, 1, 1],
  'round-hq-plate-1x1-round': [1, 1, 1],
  'round-hq-plate-1x2': [2, 1, 1],
  'round-hq-plate-1x4': [4, 1, 1],
  'round-hq-plate-1x6': [6, 1, 1],
  'round-hq-plate-1x8': [8, 1, 1],
  'round-hq-plate-2x2': [2, 2, 1],
  'round-hq-plate-2x4': [4, 2, 1],
  'round-hq-plate-2x6': [6, 2, 1],
  'round-hq-plate-2x8': [8, 2, 1],
  'round-hq-plate-4x4': [4, 4, 1],
  'round-hq-plate-4x6': [6, 4, 1],
  'round-hq-plate-4x8': [8, 4, 1],
  'round-hq-plate-corner': [2, 2, 1],
  'none-hq-plate-1x1': [1, 1, 1],
  'none-hq-plate-1x1-round': [1, 1, 1],
  'none-hq-plate-1x2': [2, 1, 1],
  'none-hq-plate-1x4': [4, 1, 1],
  'none-hq-plate-1x6': [6, 1, 1],
  'none-hq-plate-1x8': [8, 1, 1],
  'none-hq-plate-2x2': [2, 2, 1],
  'none-hq-plate-2x4': [4, 2, 1],
  'none-hq-plate-2x6': [6, 2, 1],
  'none-hq-plate-2x8': [8, 2, 1],
  'none-hq-plate-4x4': [4, 4, 1],
  'none-hq-plate-4x6': [6, 4, 1],
  'none-hq-plate-4x8': [8, 4, 1],
  'none-hq-plate-corner': [2, 2, 1],
} as const satisfies Record<string, readonly [number, number, number]>
export type BrickPiece = keyof typeof BRICK_INFO
export type LabPiece = `lab-${LabModel}`
export type Piece = BrickPiece | LabPiece

/** Raw model units: one stud, one plate layer. */
export const STUD = 0.08
export const PLATE = 0.032

export const isLab = (p: Piece): p is LabPiece => p.startsWith('lab-')
export const labModel = (p: LabPiece) => p.slice(4) as LabModel

/** A build's footprint is its scaled bounds rounded to whole studs (at least one). */
const LAB_INFO = Object.fromEntries(
  Object.entries(LAB_MODELS).map(([m, [, w, h, d]]) => [
    `lab-${m}`,
    [Math.max(1, Math.round((w * LAB_SCALE) / STUD)), Math.max(1, Math.round((d * LAB_SCALE) / STUD)), Math.ceil((h * LAB_SCALE) / PLATE)] as const,
  ]),
) as Record<LabPiece, readonly [number, number, number]>

export const PIECE_INFO: Record<Piece, readonly [number, number, number]> = { ...BRICK_INFO, ...LAB_INFO }
export const PIECES = Object.keys(PIECE_INFO) as Piece[]
export const isPiece = (p: string): p is Piece => p in PIECE_INFO
const LAB_BASE = '/assets/brick-lab'
export const piecePreview = (p: Piece) => (isLab(p) ? `${LAB_BASE}/previews/${labModel(p)}.png` : `${BASE}/previews/${p}.png`)

const url = (p: Piece) => (isLab(p) ? `${LAB_BASE}/${labModel(p)}.glb` : `${BASE}/${p}.glb`)
/** Preload the pieces the scene starts with; the rest load when first placed. */
export const preloadBricks = (pieces: Iterable<Piece>) => new Set(pieces).forEach((p) => useGLTF.preload(url(p)))

/** World units per raw unit: 16 studs ≈ one 9-unit zone. */
export const BRICK_SCALE = 7
export const STUD_W = STUD * BRICK_SCALE
/** Height of a plate's top surface (where agents stand). */
export const PLATE_TOP = PLATE * BRICK_SCALE

/**
 * Palette columns (32 px wide on a 512 px map). The pieces ship in column 9 of the lower
 * row (white); the upper row holds the saturated colors.
 */
const PALETTE = {
  cream: [1, -0.25],
  green: [3, -0.25],
  yellow: [5, -0.25],
  orange: [7, -0.25],
  red: [9, -0.25],
  blue: [11, -0.25],
  sky: [13, -0.25],
  purple: [15, -0.25],
  black: [1, 0],
  grey: [3, 0],
  slate: [5, 0],
  steel: [7, 0],
  white: [9, 0],
  clay: [11, 0],
  brown: [13, 0],
  tan: [15, 0],
} as const
export type BrickColor = keyof typeof PALETTE
export const BRICK_COLORS = Object.keys(PALETTE) as BrickColor[]
/** Approximate screen color of each palette column, for swatches in the editor. */
export const SWATCH: Record<BrickColor, string> = {
  cream: '#fde3c4',
  green: '#4cbf8a',
  yellow: '#ffc24a',
  orange: '#ff8a3d',
  red: '#e35b4f',
  blue: '#5b8de0',
  sky: '#b3d3f7',
  purple: '#a46ee6',
  black: '#3b3a42',
  grey: '#858aa0',
  slate: '#4c4f60',
  steel: '#b6bdd6',
  white: '#f2f2f6',
  clay: '#e0906c',
  brown: '#a3613f',
  tan: '#ecbb92',
}

const materials = new Map<string, MeshStandardMaterial>()

export function materialFor(base: MeshStandardMaterial, color: BrickColor): MeshStandardMaterial {
  let m = materials.get(color)
  if (!m) {
    const [col, dv] = PALETTE[color]
    const map = (base.map as Texture).clone()
    map.offset.set((col - 9) / 16, dv)
    map.needsUpdate = true
    m = base.clone()
    m.map = map
    m.roughness = 0.55
    materials.set(color, m)
  }
  return m
}

export function usePiece(piece: BrickPiece): { geometry: BufferGeometry; base: MeshStandardMaterial } {
  const { scene } = useGLTF(url(piece))
  return useMemo(() => {
    let mesh: Mesh | undefined
    scene.traverse((o) => {
      if (!mesh && (o as Mesh).isMesh) mesh = o as Mesh
    })
    return { geometry: mesh!.geometry, base: mesh!.material as MeshStandardMaterial }
  }, [scene])
}

/**
 * A Brick Lab build, centered on its footprint, at its own colors. A ghost (the piece in hand
 * in edit mode) is see-through.
 */
export function LabBuild({ piece, ghost = false, onClick, onPointerOver, onPointerOut }: { piece: LabPiece; ghost?: boolean; onClick?: (e: ThreeEvent<MouseEvent>) => void; onPointerOver?: () => void; onPointerOut?: () => void }) {
  const { scene } = useGLTF(url(piece))
  const [, , , , cx, cz] = LAB_MODELS[labModel(piece)]
  const model = useMemo(() => {
    const m = scene.clone()
    m.traverse((o) => {
      const mesh = o as Mesh
      if (!mesh.isMesh) return
      mesh.castShadow = !ghost
      mesh.receiveShadow = !ghost
      if (ghost) {
        const see = (mat: Material) => Object.assign(mat.clone(), { transparent: true, opacity: 0.55, depthWrite: false })
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map(see) : see(mesh.material)
        mesh.renderOrder = 10
      }
    })
    return m
  }, [scene, ghost])
  return (
    <group scale={LAB_SCALE} onClick={onClick} onPointerOver={onPointerOver} onPointerOut={onPointerOut}>
      <primitive object={model} position={[-cx, 0, -cz]} />
    </group>
  )
}

/** One piece. `at` = [x studs, y plate layers, z studs] of the piece's center / bottom. */
export function Brick({ piece, color, at, rot = 0 }: { piece: Piece; color: BrickColor; at: [number, number, number]; rot?: number }) {
  if (isLab(piece))
    return (
      <group position={[at[0] * STUD, at[1] * PLATE, at[2] * STUD]} rotation-y={rot}>
        <LabBuild piece={piece} />
      </group>
    )
  return <KitBrick piece={piece} color={color} at={at} rot={rot} />
}

function KitBrick({ piece, color, at, rot = 0 }: { piece: BrickPiece; color: BrickColor; at: [number, number, number]; rot?: number }) {
  const { geometry, base } = usePiece(piece)
  return (
    <mesh
      geometry={geometry}
      material={materialFor(base, color)}
      position={[at[0] * STUD, at[1] * PLATE, at[2] * STUD]}
      rotation-y={rot}
      castShadow
      receiveShadow
    />
  )
}

export type BrickSpec = [piece: Piece, color: BrickColor, x: number, y: number, z: number, rot?: number]

/** A set of pieces in stud space, scaled into world units. */
export function Build({ parts, position, rotation = 0 }: { parts: BrickSpec[]; position?: [number, number, number]; rotation?: number }) {
  return (
    <group position={position} rotation-y={rotation} scale={BRICK_SCALE}>
      {parts.map(([piece, color, x, y, z, rot], i) => (
        <Brick key={i} piece={piece} color={color} at={[x, y, z]} rot={rot} />
      ))}
    </group>
  )
}
