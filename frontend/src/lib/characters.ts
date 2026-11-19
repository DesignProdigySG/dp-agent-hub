/**
 * The models an agent can be shown as: the hub's own cast (one per agent role, built on the
 * Kenney rig, so they share its clips) and the Kenney Mini Characters (CC0).
 */
type Clip = 'idle' | 'holding-right' | 'holding-left' | 'holding-both'

/** Cast members hold their prop up (their signature pose) instead of the plain idle. */
const CAST: Record<string, Clip> = {
  'the-data-doctor': 'holding-left',
  'the-qualifier': 'holding-right',
  'the-designer': 'holding-both',
  'the-private-investigator': 'holding-right',
  'the-campaigner': 'holding-right',
  'the-auditor': 'holding-left',
  'the-flight-attendant': 'idle',
  'the-project-manager': 'idle',
}

const KENNEY = ['female-a', 'male-a', 'female-b', 'male-b', 'female-c', 'male-c', 'female-d', 'male-d', 'female-e', 'male-e', 'female-f', 'male-f']

export const CHARACTERS = [...Object.keys(CAST), ...KENNEY]

const isCast = (c: string) => c in CAST
const KENNEY_BASE = '/assets/kenney/mini-characters'
export const characterModel = (c: string) => (isCast(c) ? `/assets/characters/${c}.glb` : `${KENNEY_BASE}/character-${c}.glb`)
export const characterPreview = (c: string) => (isCast(c) ? `/assets/characters/${c}.png` : `${KENNEY_BASE}/previews/character-${c}.png`)
/** What "standing still" plays for this character. */
export const idlePose = (c: string): Clip => CAST[c] ?? 'idle'
/** Head-and-shoulders crop of the preview for round badges (the cast renders have more margin). */
export const badgeCrop = (c: string) => (isCast(c) ? { width: '270%', left: '-80%', top: '-42%' } : { width: '200%', left: '-50%', top: '-6%' })
export const characterLabel = (c: string) =>
  (isCast(c) ? c.replace(/^the-/, 'The ').replace(/^./, (x) => x.toUpperCase()) : c).replace(/-/g, ' ')

/** The agent's chosen character, or a stable pick from its id when none is set. */
export function characterOf(agent: { id: string; character?: string }): string {
  if (agent.character && CHARACTERS.includes(agent.character)) return agent.character
  let h = 0
  for (const ch of agent.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return KENNEY[h % KENNEY.length]
}
