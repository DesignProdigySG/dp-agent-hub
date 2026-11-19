/**
 * Each zone's name as a printed floor tile at its inner corner, by the walkway: a clean white
 * tile with the name in the zone's color, turned like the Marketo tile so it reads upright
 * from the default camera. It lies flush on the baseplate, so agents walk over it.
 */
import { useMemo } from 'react'
import { CanvasTexture, SRGBColorSpace } from 'three'

import type { Zone } from '../../types/contract'
import { PLATE_TOP, STUD_W } from './bricks'
import { ZONES } from './layout'
import { zoneStuds } from './placement'

const SIZE_STUDS = 6
const THICK = 0.2 // covers the baseplate's studs
const PAPER = '#fdfcfb'

const SIGNS: Record<Zone, { lines: string[]; ink: string }> = {
  database: { lines: ['Database'], ink: '#2f5fb3' },
  campaigns: { lines: ['Campaigns'], ink: '#d45f12' },
  design_studio: { lines: ['Design', 'Studio'], ink: '#7a45c4' },
  break_room: { lines: ['Break', 'Room'], ink: '#23845a' },
}

function paint({ lines, ink }: (typeof SIGNS)[Zone]): CanvasTexture {
  const px = 512
  const c = document.createElement('canvas')
  c.width = c.height = px
  const g = c.getContext('2d')!
  g.fillStyle = PAPER
  g.fillRect(0, 0, px, px)
  g.strokeStyle = ink
  g.lineWidth = 14
  g.strokeRect(22, 22, px - 44, px - 44)
  // Turned -45° to read upright from the default camera (see FloorLogo).
  g.save()
  g.translate(px / 2, px / 2)
  g.rotate(-Math.PI / 4)
  g.fillStyle = ink
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  // The text runs along the tile's diagonal (724 px). The largest size at which every line
  // fits inside the border, where the diamond narrows away from its middle.
  let size = 120
  const offset = (i: number) => (i - (lines.length - 1) / 2) * size * 1.02
  const fits = () => {
    g.font = `800 ${size}px system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif` // installed, so ready when this paints
    return lines.every((l, i) => g.measureText(l.toUpperCase()).width <= 560 - 2 * (Math.abs(offset(i)) + size / 2))
  }
  while (size > 24 && !fits()) size -= 4
  const step = size * 1.02
  lines.forEach((l, i) => g.fillText(l.toUpperCase(), 0, (i - (lines.length - 1) / 2) * step))
  g.fillRect(-70, ((lines.length + 1) / 2) * step - size * 0.25, 140, 12) // a short rule under the name
  g.restore()
  const t = new CanvasTexture(c)
  t.colorSpace = SRGBColorSpace
  t.anisotropy = 8
  return t
}

function ZoneSign({ zone }: { zone: Zone }) {
  const texture = useMemo(() => paint(SIGNS[zone]), [zone])
  const c = zoneStuds(zone)
  // the corner nearest the scene's center, pulled in by half the tile
  const at = (v: number) => (v - Math.sign(v) * (8 - SIZE_STUDS / 2)) * STUD_W
  const size = SIZE_STUDS * STUD_W
  return (
    <mesh position={[at(c.x), PLATE_TOP + THICK / 2, at(c.z)]} receiveShadow>
      <boxGeometry args={[size, THICK, size]} />
      {[0, 1, 2, 3, 4, 5].map((i) =>
        i === 2 ? (
          <meshStandardMaterial key={i} attach={`material-${i}`} map={texture} roughness={0.9} />
        ) : (
          <meshStandardMaterial key={i} attach={`material-${i}`} color={PAPER} roughness={0.9} />
        ),
      )}
    </mesh>
  )
}

export function ZoneSigns() {
  return (
    <>
      {ZONES.map((z) => (
        <ZoneSign key={z} zone={z} />
      ))}
    </>
  )
}
