/**
 * The Spatial view's decor: bricks and Brick Lab builds on a world stud grid, editable in edit mode.
 *
 * Coordinates are studs from the scene origin (x / z, piece centers) and plate layers (y,
 * the piece's bottom). Zones are fixed 16 x 16-stud baseplates and the walkway is fixed
 * tiling; everything placed on them is decor.
 */
import type { Zone } from '../../types/contract'
import { isPiece, PIECE_INFO, STUD_W, type BrickColor, type Piece } from './bricks'
import { ZONE_INFO, ZONES } from './layout'

export interface Placed {
  piece: Piece
  color: BrickColor
  x: number
  y: number
  z: number
  rot: 0 | 1 | 2 | 3 // quarter turns
}

/** [piece, color, x, z, quarter turns, layer]; x / z in world studs, layer 1 = on a baseplate. */
type Spec = [piece: Piece, color: BrickColor, x: number, z: number, rot?: Placed['rot'], y?: number]

/**
 * The office a fresh hub starts with. Zones are 16 x 16 studs around (±12, ±12); the camera
 * looks in from +x / +z, so tall pieces stand along each zone's back (-x / -z) edges, the
 * middle stays open for the agents, and the inner corner (by the walkway) holds the zone's
 * floor sign (ZoneSigns). Builds face +z at rot 0; rot 1 faces +x, 2 faces -z, 3 faces -x.
 */
const LAYOUT: Record<Zone, Spec[]> = {
  // a server room: racks and a screen along the back, data stores and the desk at the side
  database: [
    ['lab-server-rack', 'white', -19, -19],
    ['lab-server-rack', 'white', -17, -19],
    ['lab-server-rack', 'white', -15, -19],
    ['lab-server-rack', 'white', -13, -19],
    ['lab-dashboard-screen', 'white', -9.5, -19.5],
    ['lab-router', 'white', -6, -19.5],
    ['lab-database', 'white', -18.5, -15.5, 1],
    ['lab-database', 'white', -18.5, -12.5, 1],
    ['lab-desk-setup', 'white', -18.5, -8.5, 1],
    ['lab-office-chair', 'white', -16, -8, 3],
    ['lab-plant-snake', 'white', -19, -5],
  ],
  // the campaign war room: the plan on the walls, the funnel, ready to launch
  campaigns: [
    ['lab-kanban-board', 'white', 6, -19.5],
    ['lab-video-wall', 'white', 12.5, -18],
    ['lab-launch-rocket', 'white', 18.5, -18.5],
    ['lab-holo-funnel', 'white', 6, -14, 1],
    ['lab-desk-setup', 'white', 18.5, -10.5, 3],
    ['lab-office-chair', 'white', 16, -10, 1],
    ['lab-water-cooler', 'white', 19.5, -5],
  ],
  // an artist's studio: boards along the back, the desk and hologram at the side
  design_studio: [
    ['lab-swatch-wall', 'white', 12.5, 4.5],
    ['lab-mood-board', 'white', 17.5, 4.5],
    ['lab-brand-hologram', 'white', 5, 12.5, 1],
    ['lab-designer-desk', 'white', 5.5, 17.5, 1],
    ['lab-drafting-stool', 'white', 8.5, 17.5],
    ['lab-softbox-light', 'white', 19, 7, 1],
    ['lab-easel', 'white', 18.5, 10, 1],
    ['lab-camera-tripod', 'white', 19, 14, 3],
    ['lab-printer-3d', 'white', 18.5, 18.5],
    ['lab-colour-fan', 'white', 12.5, 19.5, 2],
  ],
  // where agents wait between jobs: sofas, coffee, books
  break_room: [
    ['lab-plant-snake', 'white', -19, 5],
    ['lab-sofa', 'white', -16, 5],
    ['lab-sofa', 'white', -12, 5],
    ['lab-coffee-station', 'white', -19, 8.5, 1],
    ['lab-water-cooler', 'white', -19, 10.5, 1],
    ['lab-bookshelf', 'white', -19.5, 13, 1],
    ['lab-plant-tree', 'white', -18.5, 18.5],
    ['round-hq-brick-1x1-round', 'brown', -14.5, 11.5],
    ['round-hq-brick-1x1-round', 'brown', -11.5, 11.5],
    ['round-hq-plate-2x4', 'cream', -13, 12, 0, 4],
    ['lab-plant-monstera', 'white', -7.5, 18],
  ],
}

/** The decor a fresh hub starts with, on the stud grid. */
export const DEFAULT_DECOR: Placed[] = ZONES.flatMap((zone) =>
  LAYOUT[zone].map(([piece, color, x, z, rot = 0, y = 1]): Placed => {
    const [w, d] = footprint({ piece, rot })
    return { piece, color, x: snap(x, w), y, z: snap(z, d), rot }
  }),
)

/** Footprint in studs after rotation. */
export function footprint(p: Pick<Placed, 'piece' | 'rot'>): [number, number] {
  const [w, d] = PIECE_INFO[p.piece]
  return p.rot % 2 ? [d, w] : [w, d]
}

/** Center coordinate for a piece `size` studs wide whose center is near `v`, on the grid. */
export function snap(v: number, size: number): number {
  return Math.round(v - size / 2) + size / 2
}

/**
 * A zone's baseplate center in studs. Zone centers sit 12.5 studs out; the baseplate is pulled
 * in to 12 so its edges land on the same whole-stud grid as the walkway and placed pieces.
 */
export function zoneStuds(zone: Zone): { x: number; z: number } {
  const c = ZONE_INFO[zone].center
  return { x: Math.trunc(c.x / STUD_W), z: Math.trunc(c.z / STUD_W) }
}

const ZONE_STUDS = ZONES.map(zoneStuds)

/** Top of the fixed floor at a point: 1 layer on a zone baseplate or the walkway, else 0. */
export function floorAt(x: number, z: number): number {
  if (ZONE_STUDS.some((c) => Math.abs(x - c.x) < 8 && Math.abs(z - c.z) < 8)) return 1
  if ((Math.abs(z) < 4 && Math.abs(x) < 20) || (Math.abs(x) < 4 && Math.abs(z) < 20)) return 1
  return 0
}

/** Layer a piece would rest on with its center at (x, z): above the floor and any overlap. */
export function restingLayer(p: Pick<Placed, 'piece' | 'rot'>, x: number, z: number, others: Placed[]): number {
  const [w, d] = footprint(p)
  let y = Math.max(floorAt(x - w / 2 + 0.5, z - d / 2 + 0.5), floorAt(x + w / 2 - 0.5, z + d / 2 - 0.5), floorAt(x, z))
  for (const o of others) {
    const [ow, od] = footprint(o)
    if (Math.abs(o.x - x) < (w + ow) / 2 && Math.abs(o.z - z) < (d + od) / 2) y = Math.max(y, o.y + PIECE_INFO[o.piece][2])
  }
  return y
}

/** Pieces from the server: unknown ones (from a newer kit) dropped, the rest on the grid. */
export function sanitize(pieces: { piece: string; color: string; x: number; y: number; z: number; rot: number }[]): Placed[] {
  return pieces
    .filter((p) => isPiece(p.piece))
    .map((raw) => {
      const p = { ...raw, rot: (raw.rot & 3) as Placed['rot'] } as Placed
      const [w, d] = footprint(p)
      return { ...p, x: snap(p.x, w), z: snap(p.z, d) } // layouts saved before the grid fix
    })
}
