/**
 * Agent avatar: the character model chosen in the agent editor (see lib/characters).
 * The avatar sets `clip` every frame; the model cross-fades to it. Cast members stand in
 * their signature pose, holding their prop up.
 */
import { useAnimations, useGLTF } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef, type RefObject } from 'react'
import type { AnimationAction, Group, Mesh } from 'three'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'

import { CHARACTERS, characterModel, idlePose } from '../../lib/characters'

export const preloadCharacters = () => CHARACTERS.forEach((c) => useGLTF.preload(characterModel(c)))

/** Model units are ~0.78 tall; agents stand about 2 units, a third of a zone's props. */
const SCALE = 2.5
export const MODEL_HEIGHT = 0.78 * SCALE

export type Clip = 'idle' | 'walk' | 'interact-right' | 'emote-yes' | 'emote-no'

export function AgentModel({ character, clip }: { character: string; clip: RefObject<Clip> }) {
  const { scene, animations } = useGLTF(characterModel(character))
  // Skinned meshes need their own skeleton per instance; a plain clone would share bones.
  const model = useMemo(() => {
    const m = clone(scene)
    m.traverse((o) => {
      if ((o as Mesh).isMesh) o.castShadow = true
    })
    return m
  }, [scene])
  const root = useRef<Group>(null)
  const { actions } = useAnimations(animations, root)
  const playing = useRef<AnimationAction | null>(null)

  useEffect(() => () => void playing.current?.stop(), [])

  useFrame(() => {
    const want = clip.current ?? 'idle'
    const next = actions[want === 'idle' ? idlePose(character) : want]
    if (!next || next === playing.current) return
    next.reset().fadeIn(0.2).play()
    playing.current?.fadeOut(0.2)
    playing.current = next
  })

  return (
    <group ref={root} scale={SCALE}>
      <primitive object={model} />
    </group>
  )
}
