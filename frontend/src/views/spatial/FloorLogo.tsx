/**
 * The crossing where the walkways meet is one flush floor tile in Marketo purple, with the
 * rising-bars mark and the wordmark. Same height as the walkway plates, so nothing stands in
 * anyone's way.
 */
import { useMemo } from 'react'
import { CanvasTexture, SRGBColorSpace } from 'three'

import { PLATE_TOP, STUD_W } from './bricks'

const PURPLE = '#5C4C9F'
const SIZE_STUDS = 8 // the whole crossing

function paint(): CanvasTexture {
  const px = 512
  const c = document.createElement('canvas')
  c.width = c.height = px
  const g = c.getContext('2d')!
  g.fillStyle = PURPLE
  g.fillRect(0, 0, px, px)
  // Turned -45° so it reads upright from the default camera (looking in from +x, +z): the
  // tile's +x / +y map to world +x / +z, and screen-right is world (+x, -z).
  g.save()
  g.translate(px / 2, px / 2)
  g.rotate(-Math.PI / 4)
  g.fillStyle = '#FFFFFF'
  const bar = 66
  const gap = 30
  const left = -(3 * bar + 2 * gap) / 2
  ;[96, 156, 216].forEach((h, i) => {
    g.beginPath()
    g.roundRect(left + i * (bar + gap), 40 - h, bar, h, 10) // the mark: three bars rising
    g.fill()
  })
  g.font = '700 88px Inter, Manrope, Arial, sans-serif'
  g.textAlign = 'center'
  g.fillText('Marketo', 0, 140)
  g.restore()
  const t = new CanvasTexture(c)
  t.colorSpace = SRGBColorSpace
  t.anisotropy = 8
  return t
}

export function FloorLogo() {
  const texture = useMemo(paint, [])
  const size = SIZE_STUDS * STUD_W
  return (
    <mesh position={[0, PLATE_TOP / 2, 0]} receiveShadow>
      <boxGeometry args={[size, PLATE_TOP, size]} />
      {/* box faces: +x, -x, +y (top, the logo), -y, +z, -z */}
      {[0, 1, 2, 3, 4, 5].map((i) =>
        i === 2 ? (
          <meshStandardMaterial key={i} attach={`material-${i}`} map={texture} roughness={0.9} />
        ) : (
          <meshStandardMaterial key={i} attach={`material-${i}`} color={PURPLE} roughness={0.9} />
        ),
      )}
    </mesh>
  )
}
