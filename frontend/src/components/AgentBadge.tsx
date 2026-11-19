import { badgeCrop, characterOf, characterPreview } from '../lib/characters'

/** Round avatar: the agent's character (head and shoulders) on its color. */
export function AgentBadge({ agent, size = 36, className = '' }: { agent: { id: string; name: string; color: string; character?: string }; size?: number; className?: string }) {
  const c = characterOf(agent)
  return (
    <span className={`relative inline-block shrink-0 overflow-hidden rounded-full ${className}`} style={{ width: size, height: size, background: agent.color }} aria-hidden>
      <img src={characterPreview(c)} alt="" draggable={false} className="absolute max-w-none" style={badgeCrop(c)} />
    </span>
  )
}
