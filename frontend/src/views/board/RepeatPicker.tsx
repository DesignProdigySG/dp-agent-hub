import { fieldClass } from '../../components/Dialog'
import type { RepeatKind } from '../../lib/api'

export interface Repeat {
  kind: 'once' | RepeatKind
  every_minutes: number
  at_time: string
  weekdays: number[]
}

export const ONCE: Repeat = { kind: 'once', every_minutes: 15, at_time: '08:00', weekdays: [0] }
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const EVERY = [
  { m: 15, label: '15 minutes' },
  { m: 30, label: '30 minutes' },
  { m: 60, label: 'hour' },
  { m: 240, label: '4 hours' },
  { m: 720, label: '12 hours' },
]
export const localTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

/** Once, every N minutes, daily at a time, or weekly on chosen days at a time. */
export function RepeatPicker({ value, onChange }: { value: Repeat; onChange: (r: Repeat) => void }) {
  const set = (patch: Partial<Repeat>) => onChange({ ...value, ...patch })
  const tab = (k: Repeat['kind'], label: string) => (
    <button
      type="button"
      key={k}
      onClick={() => set({ kind: k })}
      aria-pressed={value.kind === k}
      className={`rounded-full px-3 py-1 text-xs ${value.kind === k ? 'bg-secondary-container font-medium text-on-secondary-container' : 'text-on-surface-variant hover:bg-on-surface/5'}`}
    >
      {label}
    </button>
  )
  return (
    <div className="space-y-2">
      <div className="flex w-fit flex-wrap rounded-full border border-outline-variant p-0.5" role="group" aria-label="Repeat">
        {tab('once', 'Once')}
        {tab('interval', 'Every…')}
        {tab('daily', 'Daily')}
        {tab('weekly', 'Weekly')}
      </div>
      {value.kind === 'interval' && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-on-surface-variant">Every</span>
          <select className={`${fieldClass} !w-auto`} value={EVERY.some((e) => e.m === value.every_minutes) ? value.every_minutes : 'custom'} onChange={(e) => e.target.value !== 'custom' && set({ every_minutes: Number(e.target.value) })}>
            {EVERY.map((e) => (
              <option key={e.m} value={e.m}>
                {e.label}
              </option>
            ))}
            <option value="custom">custom…</option>
          </select>
          <input type="number" min={5} step={5} aria-label="Minutes" className={`${fieldClass} !w-24 tabular-nums`} value={value.every_minutes} onChange={(e) => set({ every_minutes: Number(e.target.value) })} />
          <span className="text-on-surface-variant">minutes (min 5)</span>
        </div>
      )}
      {(value.kind === 'daily' || value.kind === 'weekly') && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {value.kind === 'weekly' &&
            DAYS.map((d, i) => (
              <button
                type="button"
                key={d}
                aria-pressed={value.weekdays.includes(i)}
                onClick={() => set({ weekdays: value.weekdays.includes(i) ? value.weekdays.filter((x) => x !== i) : [...value.weekdays, i].sort() })}
                className={`h-8 w-11 rounded-full text-xs ${value.weekdays.includes(i) ? 'bg-primary text-on-primary' : 'border border-outline-variant text-on-surface-variant'}`}
              >
                {d}
              </button>
            ))}
          <span className="text-on-surface-variant">at</span>
          <input type="time" aria-label="Time" className={`${fieldClass} !w-32`} value={value.at_time} onChange={(e) => set({ at_time: e.target.value })} />
          <span className="text-xs text-on-surface-variant">{localTz()}</span>
        </div>
      )}
    </div>
  )
}
