/**
 * The park around the office (layout in parkLayout.ts). The ground is one painted texture (grass,
 * stone paths, flower-bed soil, the pond's shore); everything standing on it is instanced, so
 * the whole park is a couple of dozen draw calls. The pond ripples, ducks paddle about, and
 * the fountains play. At night (dark theme) it's moonlit and the lamps glow.
 */
import { useFrame } from '@react-three/fiber'
import { useLayoutEffect, useMemo, useRef, type ReactNode } from 'react'
import {
  BoxGeometry,
  CanvasTexture,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DodecahedronGeometry,
  IcosahedronGeometry,
  InstancedMesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  RingGeometry,
  Shape,
  ShapeGeometry,
  SphereGeometry,
  SRGBColorSpace,
  type Group,
  type Mesh,
} from 'three'

import { useHub } from '../../store/hub'
import type { P } from './layout'
import {
  ARM,
  EXTENT,
  FOUNTAINS,
  LOOP_R,
  LOOP_W,
  OFFICE,
  PARK,
  PLAZA_R,
  POND,
  pondOutline,
  pondPoint,
  SPUR_W,
  spurEnd,
  rng,
  type Tree,
} from './parkLayout'

const GRASS = '#7fbf5a'
const STONE = '#ddd2ba'
const WATER = '#4aa3c9'
/** Moonlight: every park color is multiplied by this in the dark theme. */
const NIGHT = '#6f7c99'

// Unit shapes with their base at y = 0, scaled per instance
const box = new BoxGeometry(1, 1, 1).translate(0, 0.5, 0)
const trunk = new CylinderGeometry(0.1, 0.16, 1, 6).translate(0, 0.5, 0)
const blob = new IcosahedronGeometry(1, 0)
const cone = new ConeGeometry(1, 1, 7).translate(0, 0.5, 0)
const ball = new SphereGeometry(1, 6, 4)
const rock = new DodecahedronGeometry(1, 0)
const stalk = new CylinderGeometry(0.02, 0.025, 1, 4).translate(0, 0.5, 0)
const pad = new CylinderGeometry(1, 1, 0.02, 10)
const pole = new CylinderGeometry(0.045, 0.06, 1, 6).translate(0, 0.5, 0)

interface Item {
  p: [number, number, number]
  s: number | [number, number, number]
  r?: number
  c: string
}

/** One instanced mesh for many copies of a shape, each with its own place, size and color. */
function Many({ items, shadow = true, children }: { items: Item[]; shadow?: boolean; children: ReactNode }) {
  const ref = useRef<InstancedMesh>(null)
  useLayoutEffect(() => {
    const mesh = ref.current!
    const o = new Object3D()
    const c = new Color()
    items.forEach((it, i) => {
      o.position.set(...it.p)
      o.rotation.set(0, it.r ?? 0, 0)
      if (typeof it.s === 'number') o.scale.setScalar(it.s)
      else o.scale.set(...it.s)
      o.updateMatrix()
      mesh.setMatrixAt(i, o.matrix)
      mesh.setColorAt(i, c.set(it.c))
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    mesh.computeBoundingSphere()
  }, [items])
  return (
    <instancedMesh key={items.length} ref={ref} args={[undefined, undefined, items.length]} castShadow={shadow} receiveShadow>
      {children}
    </instancedMesh>
  )
}

/** The ground: grass, stone paths with pavers, bed soil, the pond's sandy shore. */
function paintGround(): CanvasTexture {
  const px = 2048
  const k = px / (2 * EXTENT)
  const X = (v: number) => (v + EXTENT) * k // world x / z -> canvas x / y
  const r = rng(7)
  const c = document.createElement('canvas')
  c.width = c.height = px
  const g = c.getContext('2d')!

  // grass: mottled, then speckled
  g.fillStyle = GRASS
  g.fillRect(0, 0, px, px)
  const greens = ['#76b552', '#86c463', '#6eaa4c', '#8fca6a', '#7cba57']
  g.globalAlpha = 0.28
  for (let i = 0; i < 9000; i++) {
    g.fillStyle = greens[i % greens.length]
    g.beginPath()
    g.arc(r() * px, r() * px, (0.3 + r() * 1.3) * k, 0, Math.PI * 2)
    g.fill()
  }
  g.globalAlpha = 0.35
  for (let i = 0; i < 24000; i++) {
    g.fillStyle = r() < 0.5 ? '#5f9a40' : '#9bd474'
    g.fillRect(r() * px, r() * px, 2, 2)
  }
  // soft shade under far trees, where the shadow map doesn't reach
  g.globalAlpha = 0.16
  g.fillStyle = '#2f5a24'
  for (const t of PARK.trees) {
    g.beginPath()
    g.arc(X(t.x + 0.4), X(t.z + 0.2), t.size * 1.2 * k, 0, Math.PI * 2)
    g.fill()
  }
  g.globalAlpha = 1

  // flower-bed soil
  g.fillStyle = '#6b4f35'
  for (const b of PARK.beds) g.fillRect(X(b.x - b.w / 2), X(b.z - b.d / 2), b.w * k, b.d * k)
  for (const f of FOUNTAINS) {
    g.beginPath()
    g.arc(X(f.x), X(f.z), (PLAZA_R + 1.1) * k, 0, Math.PI * 2)
    g.arc(X(f.x), X(f.z), (PLAZA_R + 0.2) * k, 0, Math.PI * 2, true)
    g.fill()
  }

  // the pond's bed: sandy shore, wet edge, darker toward the middle
  const ring = (pts: P[]) => {
    g.beginPath()
    pts.forEach((p, i) => (i ? g.lineTo(X(p.x), X(p.z)) : g.moveTo(X(p.x), X(p.z))))
    g.closePath()
    g.fill()
  }
  g.fillStyle = '#dccb94'
  ring(pondOutline(1.2))
  g.fillStyle = '#b39f69'
  ring(pondOutline(1.04))
  const deep = g.createRadialGradient(X(POND.x), X(POND.z), 0, X(POND.x), X(POND.z), POND.a * k)
  deep.addColorStop(0, '#1f5a73')
  deep.addColorStop(1, '#4f9fb4')
  g.fillStyle = deep
  ring(pondOutline(0.98))

  // paths on their own layer: stone, pavers clipped to it, a darker edging behind
  const pc = document.createElement('canvas')
  pc.width = pc.height = px
  const pg = pc.getContext('2d')!
  const shapes = (grow: number) => {
    pg.beginPath()
    for (const s of [-1, 1]) {
      pg.rect(X(s > 0 ? OFFICE - 0.3 : -EXTENT), X(-ARM - grow), (EXTENT - OFFICE + 0.3) * k, (2 * ARM + 2 * grow) * k)
      pg.rect(X(-ARM - grow), X(s > 0 ? OFFICE - 0.3 : -EXTENT), (2 * ARM + 2 * grow) * k, (EXTENT - OFFICE + 0.3) * k)
    }
    for (const f of FOUNTAINS) {
      pg.moveTo(X(f.x) + (PLAZA_R + grow) * k, X(f.z))
      pg.arc(X(f.x), X(f.z), (PLAZA_R + grow) * k, 0, Math.PI * 2)
    }
    pg.fill()
    pg.lineWidth = (LOOP_W + 2 * grow) * k
    pg.beginPath()
    pg.arc(X(0), X(0), LOOP_R * k, 0, Math.PI * 2)
    pg.stroke()
    pg.lineWidth = (SPUR_W + 2 * grow) * k
    for (const f of FOUNTAINS) {
      const e = spurEnd(f)
      pg.beginPath()
      pg.moveTo(X(f.x), X(f.z))
      pg.lineTo(X(e.x), X(e.z))
      pg.stroke()
    }
  }
  pg.fillStyle = pg.strokeStyle = STONE
  shapes(0)
  pg.globalCompositeOperation = 'source-atop'
  const tones = ['#e6dcc6', '#d4c8ae', '#ded3bb', '#cdc0a4']
  const cell = 0.75 * k
  pg.strokeStyle = '#b9aa8c'
  pg.lineWidth = 1
  for (let y = 0; y < px; y += cell)
    for (let x = (Math.floor(y / cell) % 2) * (cell / 2) - cell; x < px; x += cell) {
      pg.fillStyle = tones[Math.floor(r() * tones.length)]
      pg.fillRect(x, y, cell, cell)
      pg.strokeRect(x, y, cell, cell)
    }
  pg.globalCompositeOperation = 'destination-over'
  pg.fillStyle = pg.strokeStyle = '#a89878'
  shapes(0.22)
  // fade the far ends of the paths into the grass
  pg.globalCompositeOperation = 'destination-in'
  const fade = pg.createRadialGradient(X(0), X(0), EXTENT * 0.7 * k, X(0), X(0), EXTENT * k)
  fade.addColorStop(0, '#000')
  fade.addColorStop(1, 'rgba(0,0,0,0)')
  pg.fillStyle = fade
  pg.fillRect(0, 0, px, px)
  g.drawImage(pc, 0, 0)

  const tex = new CanvasTexture(c)
  tex.colorSpace = SRGBColorSpace
  tex.anisotropy = 8
  return tex
}

function Ground({ tint }: { tint: string }) {
  const map = useMemo(paintGround, [])
  const deselect = () => useHub.getState().selectAgent(null)
  return (
    <>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.01} receiveShadow onClick={deselect}>
        <planeGeometry args={[2 * EXTENT, 2 * EXTENT]} />
        <meshStandardMaterial map={map} color={tint} roughness={1} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.03} onClick={deselect}>
        <planeGeometry args={[600, 600]} />
        <meshStandardMaterial color={new Color(GRASS).multiply(new Color(tint))} roughness={1} />
      </mesh>
    </>
  )
}

const CANOPY: Record<Tree['kind'], string[]> = {
  round: ['#4f9a45', '#5eaa4a', '#3f8a3f', '#6bb552', '#4b9c5c'],
  pine: ['#2f7a4a', '#3a8a52', '#2c6e45'],
  blossom: ['#f2a7c3', '#f7bfd3', '#eb93b5'],
}

function Trees({ tint }: { tint: string }) {
  const { trunks, blobs, cones } = useMemo(() => {
    const trunks: Item[] = []
    const blobs: Item[] = []
    const cones: Item[] = []
    for (const t of PARK.trees) {
      const colors = CANOPY[t.kind]
      const c = colors[Math.floor(t.tone * colors.length)]
      const s = t.size
      if (t.kind === 'pine') {
        trunks.push({ p: [t.x, 0, t.z], s: [s, t.trunk * 0.8, s], c: '#6e4a30' })
        cones.push({ p: [t.x, t.trunk * 0.6, t.z], s: [s * 0.95, s * 1.7, s * 0.95], r: t.rot, c })
        cones.push({ p: [t.x, t.trunk * 0.6 + s * 1.05, t.z], s: [s * 0.68, s * 1.35, s * 0.68], r: t.rot + 0.4, c })
      } else {
        trunks.push({ p: [t.x, 0, t.z], s: [s, t.trunk + 0.3, s], c: '#7a5236' })
        const top = t.trunk + s * 0.75
        blobs.push({ p: [t.x, top, t.z], s: [s, s * 0.9, s], r: t.rot, c })
        blobs.push({ p: [t.x + Math.cos(t.rot) * s * 0.5, top - s * 0.25, t.z + Math.sin(t.rot) * s * 0.5], s: s * 0.62, r: t.rot * 2, c })
      }
    }
    return { trunks, blobs, cones }
  }, [])
  return (
    <>
      <Many items={trunks}>
        <primitive object={trunk} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.9} />
      </Many>
      <Many items={blobs}>
        <primitive object={blob} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.85} flatShading />
      </Many>
      <Many items={cones}>
        <primitive object={cone} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.85} flatShading />
      </Many>
    </>
  )
}

/** Hedges, bushes, flowers, rocks, reeds, lamp posts and benches. */
function Planting({ tint, night }: { tint: string; night: boolean }) {
  const sets = useMemo(() => {
    const hedges: Item[] = PARK.hedges.map((h) => ({ p: [h.x, 0, h.z], s: [h.w, 0.42, h.d], c: '#3f8a45' }))
    const bushes: Item[] = PARK.bushes.map((b, i) => ({ p: [b.x, b.size * 0.45, b.z], s: [b.size, b.size * 0.75, b.size], r: i, c: b.color }))
    const flowers: Item[] = PARK.flowers.map((f) => ({ p: [f.x, f.size * 1.1, f.z], s: f.size, c: f.color }))
    const rocks: Item[] = PARK.rocks.map((k, i) => ({ p: [k.x, k.size * 0.2, k.z], s: [k.size, k.size * 0.6, k.size * 0.85], r: i * 1.7, c: k.color }))
    const reeds: Item[] = PARK.reeds.map((d) => ({ p: [d.x, 0, d.z], s: [1, d.size, 1], c: d.color }))
    const tops: Item[] = PARK.reeds.filter((_, i) => i % 3 === 0).map((d) => ({ p: [d.x, d.size, d.z], s: [0.04, 0.11, 0.04], c: '#6b4425' }))
    const poles: Item[] = PARK.lamps.map((l) => ({ p: [l.x, 0, l.z], s: [1, 1.5, 1], c: '#3b3f45' }))
    const bulbs: Item[] = PARK.lamps.map((l) => ({ p: [l.x, 1.6, l.z], s: 0.14, c: '#fff3cf' }))
    // benches: seat, back and two legs, turned to face the fountain
    const wood: Item[] = []
    const iron: Item[] = []
    for (const b of PARK.benches) {
      const at = (lx: number, ly: number, lz: number): [number, number, number] => [
        b.x + lx * Math.cos(b.rot) + lz * Math.sin(b.rot),
        ly,
        b.z - lx * Math.sin(b.rot) + lz * Math.cos(b.rot),
      ]
      wood.push({ p: at(0, 0.3, 0), s: [1.1, 0.07, 0.38], r: b.rot, c: '#9a6b43' })
      wood.push({ p: at(0, 0.42, -0.18), s: [1.1, 0.26, 0.06], r: b.rot, c: '#8c5f3a' })
      for (const lx of [-0.48, 0.48]) iron.push({ p: at(lx, 0, 0), s: [0.06, 0.3, 0.36], r: b.rot, c: '#3b3f45' })
    }
    return { hedges, bushes, flowers, rocks, reeds, tops, poles, bulbs, wood, iron }
  }, [])
  const glow = night ? 2.4 : 0.35
  return (
    <>
      <Many items={sets.hedges}>
        <primitive object={box} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.95} />
      </Many>
      <Many items={sets.bushes}>
        <primitive object={blob} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.9} flatShading />
      </Many>
      <Many items={sets.flowers} shadow={false}>
        <primitive object={ball} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.7} />
      </Many>
      <Many items={sets.rocks}>
        <primitive object={rock} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={1} flatShading />
      </Many>
      <Many items={sets.reeds} shadow={false}>
        <primitive object={stalk} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.9} />
      </Many>
      <Many items={sets.tops} shadow={false}>
        <primitive object={ball} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.9} />
      </Many>
      <Many items={sets.poles}>
        <primitive object={pole} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.5} metalness={0.4} />
      </Many>
      <Many items={sets.bulbs} shadow={false}>
        <primitive object={ball} attach="geometry" />
        <meshStandardMaterial color="#ffffff" emissive="#ffd98a" emissiveIntensity={glow} />
      </Many>
      <Many items={sets.wood}>
        <primitive object={box} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.8} />
      </Many>
      <Many items={sets.iron}>
        <primitive object={box} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.5} metalness={0.4} />
      </Many>
    </>
  )
}

const RIPPLE_S = 3.2 // seconds per ripple
const ringGeo = new RingGeometry(0.9, 1, 32).rotateX(-Math.PI / 2)
const hash = (n: number) => {
  const s = Math.sin(n * 12.9898) * 43758.5453
  return s - Math.floor(s)
}

/** Rings that spread and fade at random spots on the pond. */
function Ripple({ i }: { i: number }) {
  const ref = useRef<Mesh>(null)
  const material = useMemo(() => new MeshBasicMaterial({ color: '#ffffff', transparent: true, depthWrite: false }), [])
  useFrame(({ clock }) => {
    const t = clock.elapsedTime / RIPPLE_S + i / 3
    const n = Math.floor(t)
    const f = t - n
    const p = pondPoint((hash(n * 3 + i) - 0.5) * POND.a * 1.1, (hash(n * 7 + i + 0.5) - 0.5) * POND.b * 1.0)
    ref.current!.position.set(p.x, 0.05, p.z)
    ref.current!.scale.setScalar(0.15 + f * 0.85)
    material.opacity = (1 - f) * 0.45
  })
  return <mesh ref={ref} geometry={ringGeo} material={material} />
}

function Duck({ phase, body, head }: { phase: number; body: string; head: string }) {
  const ref = useRef<Group>(null)
  useFrame(({ clock }) => {
    const a = clock.elapsedTime * 0.12 + phase
    const p = pondPoint(Math.cos(a) * POND.a * 0.55, Math.sin(a) * POND.b * 0.45)
    const ahead = pondPoint(Math.cos(a + 0.01) * POND.a * 0.55, Math.sin(a + 0.01) * POND.b * 0.45)
    const g = ref.current!
    g.position.set(p.x, 0.06 + Math.sin(clock.elapsedTime * 3 + phase) * 0.012, p.z)
    g.rotation.y = Math.atan2(-(ahead.z - p.z), ahead.x - p.x) // the duck faces local +x
  })
  return (
    <group ref={ref}>
      <mesh position={[0, 0.08, 0]} scale={[0.3, 0.17, 0.2]} geometry={ball} castShadow>
        <meshStandardMaterial color={body} roughness={0.7} />
      </mesh>
      <mesh position={[-0.27, 0.13, 0]} rotation-z={0.6} scale={[0.12, 0.06, 0.1]} geometry={ball}>
        <meshStandardMaterial color={body} roughness={0.7} />
      </mesh>
      <mesh position={[0.22, 0.26, 0]} scale={0.11} geometry={ball} castShadow>
        <meshStandardMaterial color={head} roughness={0.6} />
      </mesh>
      <mesh position={[0.36, 0.24, 0]} rotation-z={-Math.PI / 2} scale={[0.04, 0.1, 0.04]} geometry={cone}>
        <meshStandardMaterial color="#f29a2e" roughness={0.6} />
      </mesh>
    </group>
  )
}

const PADS: Item[] = PARK.lilies.map((l, i) => ({ p: [l.x, 0.045, l.z], s: [l.size, 1, l.size], r: i, c: l.color }))
const BLOOMS: Item[] = PARK.lilies.filter((l) => l.bloom).map((l) => ({ p: [l.x, 0.09, l.z], s: [0.09, 0.06, 0.09], c: '#ffb3cf' }))

function Pond({ water, tint }: { water: MeshStandardMaterial; tint: string }) {
  const geometry = useMemo(() => {
    const pts = pondOutline(1)
    const shape = new Shape()
    pts.forEach((p, i) => (i ? shape.lineTo(p.x, -p.z) : shape.moveTo(p.x, -p.z)))
    return new ShapeGeometry(shape).rotateX(-Math.PI / 2)
  }, [])
  return (
    <>
      <mesh geometry={geometry} material={water} position-y={0.03} receiveShadow />
      {[0, 1, 2].map((i) => (
        <Ripple key={i} i={i} />
      ))}
      <Many items={PADS} shadow={false}>
        <primitive object={pad} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.6} />
      </Many>
      <Many items={BLOOMS} shadow={false}>
        <primitive object={ball} attach="geometry" />
        <meshStandardMaterial color={tint} roughness={0.6} />
      </Many>
      <Duck phase={0} body="#f5f1e6" head="#f5f1e6" />
      <Duck phase={2.6} body="#8b6b4a" head="#2f6b3a" />
    </>
  )
}

/** Spray from the top bowl down into the basin, and a little jet straight up. */
const RIM = 48
const JET = 20
function Spray({ material }: { material: MeshStandardMaterial }) {
  const ref = useRef<InstancedMesh>(null)
  const o = useMemo(() => new Object3D(), [])
  useFrame(({ clock }) => {
    const mesh = ref.current!
    for (let i = 0; i < RIM + JET; i++) {
      const jet = i >= RIM
      const T = jet ? 1.16 : 1.04 // flight time, landing back in a bowl
      const t = (clock.elapsedTime + hash(i) * T) % T
      const a = jet ? hash(i + 99) * Math.PI * 2 : (i / RIM) * Math.PI * 2
      const radial = jet ? 0.15 * t : 0.7 + 0.55 * t
      const y = jet ? 1.72 + 2.2 * t - 2 * t * t : 1.55 + 1.0 * t - 2 * t * t
      o.position.set(Math.cos(a) * radial, y, Math.sin(a) * radial)
      o.scale.setScalar(jet ? 0.04 : 0.045)
      o.updateMatrix()
      mesh.setMatrixAt(i, o.matrix)
    }
    mesh.instanceMatrix.needsUpdate = true
  })
  return <instancedMesh ref={ref} args={[ball, material, RIM + JET]} frustumCulled={false} />
}

function Fountain({ at, water, spray, stone }: { at: P; water: MeshStandardMaterial; spray: MeshStandardMaterial; stone: string }) {
  return (
    <group position={[at.x, 0, at.z]}>
      <mesh position-y={0.225} castShadow receiveShadow>
        <cylinderGeometry args={[1.6, 1.72, 0.45, 28]} />
        <meshStandardMaterial color={stone} roughness={0.85} />
      </mesh>
      <mesh position-y={0.42} material={water}>
        <cylinderGeometry args={[1.45, 1.45, 0.04, 28]} />
      </mesh>
      <mesh position-y={0.9} castShadow>
        <cylinderGeometry args={[0.2, 0.3, 1.0, 10]} />
        <meshStandardMaterial color={stone} roughness={0.85} />
      </mesh>
      <mesh position-y={1.45} castShadow>
        <cylinderGeometry args={[0.75, 0.3, 0.25, 18]} />
        <meshStandardMaterial color={stone} roughness={0.85} />
      </mesh>
      <mesh position-y={1.575} material={water}>
        <cylinderGeometry args={[0.66, 0.66, 0.02, 18]} />
      </mesh>
      <mesh position-y={1.7} scale={0.12} geometry={ball}>
        <meshStandardMaterial color={stone} roughness={0.85} />
      </mesh>
      <Spray material={spray} />
    </group>
  )
}

export function Park() {
  const night = useHub((s) => s.theme) === 'dark'
  const tint = night ? NIGHT : '#ffffff'
  const { water, spray, stone } = useMemo(() => {
    const t = new Color(tint)
    return {
      water: new MeshStandardMaterial({ color: new Color(WATER).multiply(t), roughness: 0.08, metalness: 0.1, transparent: true, opacity: 0.82 }),
      spray: new MeshStandardMaterial({ color: new Color('#e4f5ff').multiply(t), emissive: '#9fd6ef', emissiveIntensity: night ? 0.5 : 0.15, transparent: true, opacity: 0.85 }),
      stone: '#' + new Color('#d8d0c2').multiply(t).getHexString(),
    }
  }, [tint, night])
  return (
    <>
      <Ground tint={tint} />
      <Trees tint={tint} />
      <Planting tint={tint} night={night} />
      <Pond water={water} tint={tint} />
      {FOUNTAINS.map((f, i) => (
        <Fountain key={i} at={f} water={water} spray={spray} stone={stone} />
      ))}
    </>
  )
}
