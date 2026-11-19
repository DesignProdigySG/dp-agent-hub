import { useFrame } from '@react-three/fiber'
import { useCallback, useEffect, useRef } from 'react'
import type { Group, Mesh, MeshBasicMaterial } from 'three'

import { characterOf } from '../../lib/characters'
import { useHub } from '../../store/hub'
import { pendingApprovalFor } from '../../store/reduce'
import type { AgentProfile, AgentState } from '../../types/contract'
import { AgentModel, MODEL_HEIGHT, type Clip } from './AgentModel'
import { PLATE_TOP } from './bricks'
import { useLabel } from './labels'
import { getMotion, inTalk, step, STROLL_SPEED, WALK_SPEED, wander } from './motion'
import { useScene } from './sceneStore'
import { useSpeech } from './speech'
import { newsFor, THOUGHT_ICON, thoughtFor, useSeen, WORK_ICON, type Thought } from './thoughts'

const CLIPS: Record<AgentState, Clip> = {
  IDLE: 'idle',
  TRAVELING: 'walk',
  BUSY: 'interact-right',
  NEEDS_HELP: 'emote-yes',
  ERROR: 'emote-no',
}

function lerpAngle(a: number, b: number, t: number) {
  const d = ((b - a + Math.PI * 3) % (Math.PI * 2)) - Math.PI
  return a + d * t
}

function openAgent(agentId: string) {
  const ui = useHub.getState()
  ui.selectAgent(agentId)
  const approval = pendingApprovalFor(ui.approvals, ui.statuses[agentId]?.task_id)
  if (approval) ui.review(approval.id)
}

export function AgentAvatar({ profile, errorColor }: { profile: AgentProfile; errorColor: string }) {
  const root = useRef<Group>(null)
  const clip = useRef<Clip>('idle')
  const ring = useRef<Mesh>(null)
  const selected = useHub((s) => s.selectedAgentId === profile.id)

  useFrame(({ clock }, dt) => {
    const m = getMotion(profile.id)
    if (!m || !root.current) return
    const live = useHub.getState().statuses[profile.id]?.state
    if ((live ?? 'IDLE') === 'IDLE' && !inTalk(profile.id)) wander(profile.id, m, clock.elapsedTime) // idle: stroll round its zone
    const moving = step(m, Math.min(dt, 0.1), m.strolling ? STROLL_SPEED : WALK_SPEED)
    root.current.position.set(m.pos.x, PLATE_TOP, m.pos.z)
    root.current.rotation.y = lerpAngle(root.current.rotation.y, m.heading, Math.min(dt * (m.strolling ? 5 : 10), 1))
    clip.current = moving ? 'walk' : CLIPS[live ?? 'IDLE']
    if (ring.current) {
      const t = clock.elapsedTime
      const pulse = live === 'BUSY' && !moving
      ring.current.scale.setScalar(pulse ? 1 + ((t * 0.8) % 1) * 0.6 : selected ? 1.15 : 1)
      const mat = ring.current.material as MeshBasicMaterial
      mat.opacity = pulse ? 1 - ((t * 0.8) % 1) * 0.7 : selected ? 0.9 : 0.55
      mat.color.set(live === 'ERROR' ? errorColor : profile.color)
    }
  })

  return (
    <group
      ref={root}
      onClick={(e) => {
        if (useScene.getState().editing) return // clicks build the space in edit mode
        e.stopPropagation()
        openAgent(profile.id)
      }}
      onPointerOver={() => (document.body.style.cursor = 'pointer')}
      onPointerOut={() => (document.body.style.cursor = '')}
    >
      <AgentModel character={characterOf(profile)} clip={clip} />
      {/* the agent's color, at its feet: identity, selection and a pulse while working */}
      <mesh ref={ring} rotation-x={-Math.PI / 2} position={[0, 0.13, 0]}>
        <ringGeometry args={[0.55, 0.7, 40]} />
        <meshBasicMaterial color={profile.color} transparent opacity={0.55} depthWrite={false} />
      </mesh>
    </group>
  )
}

/**
 * A Sims-style thought cloud: white puffs with trailing bubbles down to the head. Help and news
 * are buttons (open the agent: its approval, or what it finished).
 */
function ThoughtCloud({ thought, icon, color, onOpen }: { thought: Thought; icon: string; color: string; onOpen: () => void }) {
  // fixed inks (the cloud is white in both themes); work in progress wears the agent's own color
  const ink = { help: '#d93025', news: '#e09a00', error: '#4a4f5c', talking: '#3b6fd8', working: color }[thought]
  const label = { help: 'Needs your help', news: 'Has something to tell you', error: 'Something went wrong', talking: 'Talking', working: 'Working' }[thought]
  const clickable = thought === 'help' || thought === 'news' || thought === 'error'
  const Tag = clickable ? 'button' : 'div'
  return (
    <Tag onClick={clickable ? onOpen : undefined} title={label} aria-label={label} className={`thought-cloud thought-${thought} ${clickable ? 'pointer-events-auto cursor-pointer' : ''}`}>
      <span className="material-symbols-rounded filled !text-[22px]" style={{ color: ink }}>{icon}</span>
      <span className="thought-trail" aria-hidden />
    </Tag>
  )
}

/** Name tag (with the thought cloud and speech) floating above an agent; lives in the overlay. */
export function AgentLabel({ profile }: { profile: AgentProfile }) {
  const status = useHub((s) => s.statuses[profile.id])
  const selected = useHub((s) => s.selectedAgentId === profile.id)
  const saying = useSpeech((s) => s.lines[profile.id])
  const talking = useSpeech((s) => s.talking.includes(profile.id))
  const tasks = useHub((s) => s.tasks)
  const seen = useSeen((s) => s.seen)
  const state = status?.state ?? 'IDLE'
  const news = newsFor(profile.id, tasks, seen)
  const newsKey = news.join(',')
  useEffect(() => {
    if (selected && newsKey) useSeen.getState().markSeen(newsKey.split(','))
  }, [selected, newsKey])
  const thought = thoughtFor({ state, talking, saying: !!saying, news: news.length > 0 })
  const anchor = useCallback(() => {
    const m = getMotion(profile.id)
    return m ? { x: m.pos.x, y: PLATE_TOP + MODEL_HEIGHT + 0.25, z: m.pos.z } : null
  }, [profile.id])
  const ref = useLabel(`agent:${profile.id}`, anchor)

  return (
    <div ref={ref} className="pointer-events-none absolute left-0 top-0 z-20" style={{ visibility: 'hidden' }}>
      <div className="flex origin-bottom flex-col items-center gap-1">
        {saying && (
          <div className="speech-pop relative max-w-[220px] rounded-2xl border-2 bg-surface px-3 py-1.5 text-center text-[13px] font-medium leading-snug shadow-md" style={{ borderColor: profile.color }}>
            {saying}
            <span className="absolute left-1/2 top-full -ml-1.5 h-0 w-0 border-x-[6px] border-t-[7px] border-x-transparent" style={{ borderTopColor: profile.color }} />
          </div>
        )}
        {thought && <ThoughtCloud thought={thought} icon={thought === 'working' ? WORK_ICON[status?.zone ?? profile.home_zone] : THOUGHT_ICON[thought]} color={profile.color} onOpen={() => openAgent(profile.id)} />}
        <div
          className={`w-max max-w-[180px] rounded-xl border bg-surface/95 px-2.5 py-1 text-center text-[11px] leading-tight shadow-sm backdrop-blur ${
            selected ? 'border-primary' : 'border-outline-variant'
          }`}
        >
          <div className="truncate font-semibold" style={{ color: profile.color }}>
            {profile.name}
          </div>
          {selected && status && state !== 'IDLE' && <div className="text-on-surface-variant">{status.status_text}</div>}
        </div>
      </div>
    </div>
  )
}
