import { Icon } from '../components/ui'
import { useHub, type View } from '../store/hub'

const ITEMS: { id: View; label: string; icon: string }[] = [
  { id: 'board', label: 'Board', icon: 'view_kanban' },
  { id: 'calendar', label: 'Calendar', icon: 'calendar_month' },
  { id: 'spatial', label: 'Spatial', icon: 'view_in_ar' },
  { id: 'agents', label: 'Agents', icon: 'smart_toy' },
  { id: 'insights', label: 'Insights', icon: 'insights' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
]

/** M3 navigation rail with a FAB for new tasks. */
export function LeftSidebar() {
  const view = useHub((s) => s.view)
  const setView = useHub((s) => s.setView)
  const openNewTask = useHub((s) => s.openNewTask)

  return (
    <nav className="flex w-20 shrink-0 flex-col items-center gap-3 pt-2">
      <button
        onClick={() => openNewTask()}
        title="New task"
        className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-primary-container text-on-primary-container shadow-sm transition hover:shadow-md"
      >
        <Icon name="add" className="!text-[26px]" />
      </button>
      {ITEMS.map((it) => {
        const active = view === it.id
        return (
          <button key={it.id} onClick={() => setView(it.id)} className="group flex flex-col items-center gap-1">
            <span
              className={`grid h-8 w-14 place-items-center rounded-full transition ${
                active ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant group-hover:bg-on-surface/5'
              }`}
            >
              <Icon name={it.icon} filled={active} />
            </span>
            <span className={`text-xs ${active ? 'font-semibold text-on-surface' : 'text-on-surface-variant'}`}>{it.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
