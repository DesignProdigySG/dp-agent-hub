
import { metricLabel } from '../../components/ui'
import { useHub } from '../../store/hub'
import type { AgentStatus, Zone } from '../../types/contract'
import { Build, type BrickColor, type BrickSpec } from './bricks'
import { ZONE_INFO } from './layout'
import { zoneStuds } from './placement'


export function zoneKpis(zone: Zone, statuses: AgentStatus[]): [string, string | number][] {
  if (zone === 'break_room') {
    const active = statuses.filter((s) => s.state !== 'IDLE').length
    const alerts = statuses.filter((s) => s.state === 'NEEDS_HELP' || s.state === 'ERROR').length
    return [['active_agents', active], ['idle_agents', statuses.length - active], ['alerts', alerts]]
  }
  const merged: Record<string, string | number> = {}
  for (const s of statuses) Object.assign(merged, s.metrics)
  return ZONE_INFO[zone].kpis.map((k) => [k, merged[k] ?? '—'])
}

const ZONE_BRICK: Record<Zone, BrickColor> = {
  database: 'blue',
  campaigns: 'orange',
  design_studio: 'purple',
  break_room: 'green',
}

/** A 16 × 16-stud baseplate of 4 × 8 plates. */
const baseplate = (color: BrickColor) => [-4, 4].flatMap((x) => [-6, -2, 2, 6].map((z): BrickSpec => ['round-hq-plate-4x8', color, x, 0, z]))

export function ZonePlatform({ zone }: { zone: Zone }) {
  const c = zoneStuds(zone)
  return <Build parts={baseplate(ZONE_BRICK[zone]).map(([piece, color, x, y, z]): BrickSpec => [piece, color, c.x + x, y, c.z + z])} />
}

/** Screen color of each zone's bricks, for the HUD legend. */
const ZONE_SWATCH: Record<Zone, string> = {
  database: '#5b8de0',
  campaigns: '#ff8a3d',
  design_studio: '#a46ee6',
  break_room: '#3fae7f',
}

/** One zone's KPIs, for the strip above the scene. */
export function ZoneCard({ zone }: { zone: Zone }) {
  const info = ZONE_INFO[zone]
  const statuses = useHub((s) => s.statuses)
  const kpis = zoneKpis(zone, Object.values(statuses))
  return (
    <div className="min-w-[150px] flex-1 rounded-xl border border-outline-variant bg-surface/90 px-3 py-2 text-[11px] shadow-sm backdrop-blur">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-on-surface">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: ZONE_SWATCH[zone] }} />
        {info.label}
      </div>
      {kpis.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 text-on-surface-variant">
          <span>{metricLabel(k)}</span>
          <span className="font-medium tabular-nums text-on-surface">{v}</span>
        </div>
      ))}
    </div>
  )
}
