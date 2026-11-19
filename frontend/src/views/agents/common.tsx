import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Icon } from '../../components/ui'
import { api, type KnowledgeDoc, type Risk, type Skill, type ToolInfo } from '../../lib/api'

export function Card({ title, icon, description, actions, children }: { title: string; icon: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-3xl bg-surface-container p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Icon name={icon} /> {title}
          </h2>
          {description && <p className="mt-1 text-xs text-on-surface-variant">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Field({ label, help, children, className = '' }: { label: string; help?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className} role="group" aria-label={label}>
      <span className="mb-1 block text-xs font-medium text-on-surface-variant">{label}</span>
      {children}
      {help && <p className="mt-1 text-xs text-on-surface-variant">{help}</p>}
    </div>
  )
}

export function Toggle({ on, onChange, label, disabled }: { on: boolean; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:opacity-40 ${on ? 'bg-primary' : 'bg-surface-container-highest ring-1 ring-outline'}`}
    >
      <span className={`absolute top-1 h-5 w-5 rounded-full transition-all ${on ? 'left-6 bg-on-primary' : 'left-1 bg-outline'}`} />
    </button>
  )
}

const RISK: Record<Risk, { label: string; icon: string; className: string }> = {
  read: { label: 'Read', icon: 'visibility', className: 'text-on-surface-variant border-outline-variant' },
  internal: { label: 'Internal', icon: 'psychology', className: 'text-on-surface-variant border-outline-variant' },
  write: { label: 'Write', icon: 'edit', className: 'text-warning border-warning' },
  destructive: { label: 'Destructive', icon: 'warning', className: 'text-error border-error' },
}

export function RiskChip({ risk }: { risk: Risk }) {
  const r = RISK[risk]
  return (
    <span className={`inline-flex shrink-0 items-center gap-0.5 rounded-md border px-1.5 py-px text-[11px] font-medium ${r.className}`}>
      <Icon name={r.icon} className="!text-[13px]" /> {r.label}
    </span>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'error' | 'warning'; children: ReactNode }) {
  const cls = {
    info: 'bg-surface text-on-surface-variant',
    error: 'bg-error-container text-error',
    warning: 'bg-surface text-warning ring-1 ring-warning/50',
  }[tone]
  return <p className={`rounded-xl px-3 py-2 text-xs ${cls}`}>{children}</p>
}

export interface Library {
  tools: ToolInfo[]
  mcpError: string
  skills: Skill[]
  docs: KnowledgeDoc[]
  vectorSearch: boolean
  loaded: boolean
  error: string
  reload: () => void
}

/** Tool catalog, skills and knowledge documents, shared by every tab of the Agents view. */
export function useLibrary(): Library {
  const [state, setState] = useState<Omit<Library, 'reload'>>({ tools: [], mcpError: '', skills: [], docs: [], vectorSearch: false, loaded: false, error: '' })
  const reload = useCallback(() => {
    Promise.all([api.tools(), api.skills(), api.knowledge()])
      .then(([t, skills, k]) => setState({ tools: t.tools, mcpError: t.mcp_error, skills, docs: k.docs, vectorSearch: k.vector_search, loaded: true, error: '' }))
      .catch((e: Error) => setState((s) => ({ ...s, loaded: true, error: e.message })))
  }, [])
  useEffect(reload, [reload])
  return { ...state, reload }
}

/** Two-step delete button: the first click arms it. */
export function ConfirmDelete({ onConfirm, label = 'Delete', disabled }: { onConfirm: () => void; label?: string; disabled?: boolean }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(t)
  }, [armed])
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => (armed ? onConfirm() : setArmed(true))}
      className={`inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-sm font-medium transition disabled:opacity-40 ${
        armed ? 'bg-error text-on-error' : 'text-error hover:bg-error/10'
      }`}
    >
      <Icon name="delete" /> {armed ? 'Click again to confirm' : label}
    </button>
  )
}
