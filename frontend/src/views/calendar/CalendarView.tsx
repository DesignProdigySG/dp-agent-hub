import { useEffect, useMemo, useState } from 'react'

import { Button, Icon, TASK_STATUS } from '../../components/ui'
import type { Schedule } from '../../lib/api'
import { useHub } from '../../store/hub'
import { useSchedules } from '../../store/schedules'
import type { TaskOut } from '../../types/contract'

type Mode = 'month' | 'week'

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
const startOfWeek = (d: Date) => {
  const s = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  s.setDate(s.getDate() - s.getDay())
  return s
}
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)

/** A task sits on its scheduled day, or the day it was created if it ran ASAP. */
const taskDate = (t: TaskOut) => new Date(t.scheduled_for ?? t.created_at)

function TaskChip({ task, showTime }: { task: TaskOut; showTime?: boolean }) {
  const agent = useHub((s) => s.agents.find((a) => a.id === task.agent_id))
  const color = agent?.color ?? 'var(--md-primary)'
  const st = TASK_STATUS[task.status]
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        useHub.getState().selectAgent(task.agent_id)
      }}
      title={`${task.title} · ${agent?.name ?? task.agent_id} · ${st.label}`}
      className="flex w-full items-center gap-1 truncate rounded-md px-1.5 py-0.5 text-left text-[11px]"
      style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}
    >
      <Icon name={st.icon} className="!text-[13px]" filled />
      {showTime && <span className="tabular-nums opacity-80">{taskDate(task).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>}
      <span className="truncate font-medium">{task.title}</span>
    </button>
  )
}

/** A future run of a recurring schedule on `day`, or null if it doesn't run that day. */
function occurrence(s: Schedule, day: Date): string | null {
  if (!s.enabled) return null
  if (s.kind === 'interval') return `every ${s.every_minutes >= 60 && s.every_minutes % 60 === 0 ? `${s.every_minutes / 60} h` : `${s.every_minutes} min`}`
  if (s.kind === 'weekly' && !s.weekdays.includes((day.getDay() + 6) % 7)) return null
  return s.at_time
}

function RecurringChip({ s, label }: { s: Schedule; label: string }) {
  const agent = useHub((st) => st.agents.find((a) => a.id === s.agent_id))
  const color = agent?.color ?? 'var(--md-primary)'
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        useHub.getState().selectAgent(s.agent_id)
      }}
      title={`${s.title} · ${s.description_text} · ${agent?.name ?? s.agent_id}`}
      className="flex w-full items-center gap-1 truncate rounded-md border border-dashed px-1.5 py-0.5 text-left text-[11px] opacity-75"
      style={{ borderColor: color, color }}
    >
      <Icon name="event_repeat" className="!text-[13px]" />
      <span className="tabular-nums opacity-80">{label}</span>
      <span className="truncate font-medium">{s.title}</span>
    </button>
  )
}

export function CalendarView() {
  const tasks = useHub((s) => s.tasks)
  const openNewTask = useHub((s) => s.openNewTask)
  const { items: schedules, load: loadSchedules } = useSchedules()
  useEffect(() => {
    loadSchedules()
  }, [loadSchedules])
  const [mode, setMode] = useState<Mode>('month')
  const [cursor, setCursor] = useState(() => new Date())

  const byDay = useMemo(() => {
    const m = new Map<string, TaskOut[]>()
    for (const t of Object.values(tasks)) {
      if (t.archived_at) continue
      const k = dayKey(taskDate(t))
      m.set(k, [...(m.get(k) ?? []), t])
    }
    for (const list of m.values()) list.sort((a, b) => taskDate(a).getTime() - taskDate(b).getTime())
    return m
  }, [tasks])

  const days = useMemo(() => {
    if (mode === 'week') return Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(cursor), i))
    const first = startOfWeek(new Date(cursor.getFullYear(), cursor.getMonth(), 1))
    return Array.from({ length: 42 }, (_, i) => addDays(first, i))
  }, [mode, cursor])

  const shift = (dir: number) =>
    setCursor((c) => (mode === 'week' ? addDays(c, 7 * dir) : new Date(c.getFullYear(), c.getMonth() + dir, 1)))

  const today = dayKey(new Date())
  const title =
    mode === 'month'
      ? cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
      : `Week of ${days[0].toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`

  const newAt = (d: Date) => openNewTask({ date: new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9) })

  return (
    <div className="flex h-full min-h-0 flex-col rounded-3xl bg-surface-container p-4">
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold">{title}</h2>
        <Button variant="text" onClick={() => setCursor(new Date())}>
          Today
        </Button>
        <button onClick={() => shift(-1)} className="grid h-9 w-9 place-items-center rounded-full hover:bg-on-surface/5" aria-label="Previous">
          <Icon name="chevron_left" />
        </button>
        <button onClick={() => shift(1)} className="grid h-9 w-9 place-items-center rounded-full hover:bg-on-surface/5" aria-label="Next">
          <Icon name="chevron_right" />
        </button>
        <div className="flex rounded-full border border-outline-variant p-0.5 text-sm">
          {(['month', 'week'] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-full px-3 py-1 capitalize ${mode === m ? 'bg-secondary-container font-medium text-on-secondary-container' : 'text-on-surface-variant'}`}
            >
              {m}
            </button>
          ))}
        </div>
      </header>
      <div className="grid grid-cols-7 gap-px pb-1 text-center text-xs font-medium text-on-surface-variant">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
          <div key={d}>{d}</div>
        ))}
      </div>
      <div className={`grid min-h-0 flex-1 grid-cols-7 gap-1 ${mode === 'month' ? 'grid-rows-6' : 'grid-rows-1'}`}>
        {days.map((d) => {
          const list = byDay.get(dayKey(d)) ?? []
          const outside = mode === 'month' && d.getMonth() !== cursor.getMonth()
          const max = mode === 'month' ? 3 : 20
          const upcoming = addDays(d, 1) > new Date() ? schedules.flatMap((s) => {
            const label = occurrence(s, d)
            return label ? [{ s, label }] : []
          }) : []
          return (
            <div
              key={d.toISOString()}
              onClick={() => newAt(d)}
              title="Click to schedule a task on this day"
              className={`group min-h-0 cursor-pointer overflow-hidden rounded-xl bg-surface p-1.5 transition hover:ring-1 hover:ring-primary/40 ${outside ? 'opacity-50' : ''}`}
            >
              <div className="mb-1 flex items-center justify-between">
                <span
                  className={`grid h-6 min-w-6 place-items-center rounded-full px-1 text-xs tabular-nums ${
                    dayKey(d) === today ? 'bg-primary font-semibold text-on-primary' : 'text-on-surface-variant'
                  }`}
                >
                  {d.getDate()}
                </span>
                <Icon name="add" className="!text-[16px] text-on-surface-variant opacity-0 group-hover:opacity-100" />
              </div>
              <div className="space-y-0.5">
                {list.slice(0, max).map((t) => (
                  <TaskChip key={t.id} task={t} showTime={mode === 'week'} />
                ))}
                {list.length > max && <div className="px-1 text-[11px] text-on-surface-variant">+{list.length - max} more</div>}
                {upcoming.slice(0, mode === 'month' ? 2 : 20).map(({ s, label }) => (
                  <RecurringChip key={s.id} s={s} label={label} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
