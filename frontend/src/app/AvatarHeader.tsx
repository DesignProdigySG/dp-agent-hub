import { Canvas, useFrame } from '@react-three/fiber'
import { Suspense, useRef } from 'react'
import type { Group } from 'three'

import { characterOf } from '../lib/characters'
import type { AgentProfile } from '../types/contract'
import { AgentModel, MODEL_HEIGHT, type Clip } from '../views/spatial/AgentModel'

function Turntable({ character }: { character: string }) {
  const g = useRef<Group>(null)
  const clip = useRef<Clip>('idle')
  useFrame((_, dt) => g.current && (g.current.rotation.y += dt * 0.6))
  return (
    <group ref={g} position={[0, -MODEL_HEIGHT / 2, 0]}>
      <AgentModel character={character} clip={clip} />
    </group>
  )
}

/** 3D avatar header for the profile panel. */
export default function AvatarHeader({ agent }: { agent: AgentProfile }) {
  return (
    <div className="h-36 overflow-hidden rounded-2xl" style={{ background: `color-mix(in srgb, ${agent.color} 18%, var(--md-surface-container))` }}>
      <Canvas camera={{ position: [0, 0.2, 5], fov: 30 }} dpr={[1, 2]}>
        <ambientLight intensity={0.9} />
        <directionalLight position={[2, 4, 3]} intensity={1.6} />
        <Suspense fallback={null}>
          <Turntable character={characterOf(agent)} />
        </Suspense>
      </Canvas>
    </div>
  )
}
