import { useEffect, useState } from 'react'

import { AgentBadge } from '../../components/AgentBadge'
import { Dialog } from '../../components/Dialog'
import { Button, Icon, formatWhen } from '../../components/ui'
import { api, type Schedule } from '../../lib/api'
import { useHub } from '../../store/hub'
import { useSchedules } from '../../store/schedules'
import { localTz, RepeatPicker, type Repeat } from './RepeatPicker'

function EditCadence({ s, onClose }: { s: Schedule; onClose: () => void }) {
  const [repeat, setRepeat] = useState<Repeat>({ kind: s.kind, every_minutes: s.every_minutes, at_time: s.at_time, weekdays: s.weekdays })
  const [error, setError] = useState('')
  const save = async () => {
    if (repeat.kind === 'once') return setError('Use Delete to stop repeating.')
    try {
      await api.updateSchedule(s.id, { ...s, kind: repeat.kind, every_minutes: repeat.every_minutes, at_time: repeat.at_time, weekdays: repeat.weekdays, tz: s.kind === 'interval' ? localTz() : s.tz })
      await useSchedules.getState().load()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <Dialog title={`Repeat: ${s.title}`} onClose={onClose}>
      <div className="space-y-4">
        <RepeatPicker value={repeat} onChange={setRepeat} />
        {error && <p className="text-sm text-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="text" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save}>Save</Button>
        </div>
      </div>
    </Dialog>
  )
}

function Row({ s }: { s: Schedule }) {
  const agent = useHub((st) => st.agents.find((a) => a.id === s.agent_id))
  const last = useHub((st) => (s.last_task_id ? st.tasks[s.last_task_id] : undefined))
  const isAdmin = useHub((st) => st.auth.authenticated)
  const [editing, setEditing] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState('')
  const act = (fn: () => Promise<unknown>) => async () => {
    setError('')
    try {
      await fn()
      await useSchedules.getState().load()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <li className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl bg-surface px-3 py-2 ${s.enabled ? '' : 'opacity-60'}`}>
      {agent && <AgentBadge agent={agent} size={28} />}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{s.title}</div>
        <div className="truncate text-xs text-on-surface-variant">
          {s.description_text}
          {' · '}
          {s.enabled ? (s.next_run_at ? `next ${formatWhen(s.next_run_at)}` : 'not scheduled') : 'paused'}
          {last && ` · last run ${last.status.replace('_', ' ')}`}
          {s.last_note && ` · ${s.last_note}`}
        </div>
        {error && <div className="text-xs text-error">{error}</div>}
      </div>
      {isAdmin && (
        <div className="flex items-center gap-0.5">
          <Button variant="text" className="!h-8 !px-2" title={s.enabled ? 'Pause' : 'Resume'} onClick={act(() => api.updateSchedule(s.id, { ...s, enabled: !s.enabled }))}>
            <Icon name={s.enabled ? 'pause' : 'play_circle'} />
          </Button>
          <Button variant="text" className="!h-8 !px-2" title="Run now" onClick={act(() => api.runSchedule(s.id))}>
            <Icon name="play_arrow" />
          </Button>
          <Button variant="text" className="!h-8 !px-2" title="Change how often" onClick={() => setEditing(true)}>
            <Icon name="edit_calendar" />
          </Button>
          {confirm ? (
            <Button variant="danger" className="!h-8 !px-2" onClick={act(() => api.deleteSchedule(s.id))}>
              Delete?
            </Button>
          ) : (
            <Button variant="text" className="!h-8 !px-2" title="Delete schedule" onClick={() => setConfirm(true)}>
              <Icon name="delete" />
            </Button>
          )}
        </div>
      )}
      {editing && <EditCadence s={s} onClose={() => setEditing(false)} />}
    </li>
  )
}

/** Recurring tasks, above the board columns. */
export function RecurringPanel() {
  const { items, loaded, load } = useSchedules()
  const [open, setOpen] = useState(true)
  useEffect(() => {
    load()
    const t = setInterval(load, 30_000)
    return () => clearInterval(t)
  }, [load])
  if (loaded && !items.length) return null
  return (
    <section className="rounded-3xl bg-surface-container p-3">
      <button className="flex w-full items-center gap-2 px-1 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon name="event_repeat" className="!text-[18px]" />
        <h2 className="flex-1 text-sm font-semibold">Recurring</h2>
        <span className="rounded-full bg-surface-container-highest px-2 text-xs tabular-nums text-on-surface-variant">{items.length}</span>
        <Icon name={open ? 'expand_less' : 'expand_more'} />
      </button>
      {open && (
        <ul className="mt-2 grid gap-1.5 lg:grid-cols-2">
          {items.map((s) => (
            <Row key={s.id} s={s} />
          ))}
        </ul>
      )}
    </section>
  )
}
