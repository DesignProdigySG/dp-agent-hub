import type { ReactNode } from 'react'

import type { AgentState, TaskStatus } from '../types/contract'

export function Icon({ name, filled, className = '' }: { name: string; filled?: boolean; className?: string }) {
  return (
    <span aria-hidden className={`material-symbols-rounded ${filled ? 'filled' : ''} ${className}`}>
      {name}
    </span>
  )
}

export function Chip({ children, color, className = '' }: { children: ReactNode; color?: string; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-lg border border-outline-variant px-2 py-0.5 text-xs font-medium text-on-surface-variant ${className}`}
      style={color ? { borderColor: color, color } : undefined}
    >
      {children}
    </span>
  )
}

export function Button({
  children,
  onClick,
  variant = 'filled',
  disabled,
  type = 'button',
  className = '',
  title,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'filled' | 'tonal' | 'text' | 'danger'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
  title?: string
}) {
  const styles = {
    filled: 'bg-primary text-on-primary hover:shadow-md',
    tonal: 'bg-secondary-container text-on-secondary-container hover:shadow-sm',
    text: 'text-primary hover:bg-primary/10',
    danger: 'bg-error text-on-error hover:shadow-md',
  }[variant]
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-9 items-center justify-center gap-1.5 rounded-full px-4 text-sm font-medium transition disabled:opacity-40 ${styles} ${className}`}
    >
      {children}
    </button>
  )
}

export const STATE_STYLE: Record<AgentState, { label: string; dot: string; icon: string }> = {
  IDLE: { label: 'Idle', dot: 'bg-outline', icon: 'coffee' },
  TRAVELING: { label: 'Traveling', dot: 'bg-primary', icon: 'directions_walk' },
  BUSY: { label: 'Working', dot: 'bg-success', icon: 'bolt' },
  NEEDS_HELP: { label: 'Needs help', dot: 'bg-error', icon: 'front_hand' },
  ERROR: { label: 'Error', dot: 'bg-error', icon: 'error' },
}

export function StateBadge({ state }: { state: AgentState }) {
  const s = STATE_STYLE[state]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant">
      <span className={`h-2 w-2 rounded-full ${s.dot} ${state === 'NEEDS_HELP' ? 'needs-help-pulse' : ''}`} />
      {s.label}
    </span>
  )
}

export const TASK_STATUS: Record<TaskStatus, { label: string; icon: string; tone: string }> = {
  queued: { label: 'Queued', icon: 'schedule', tone: 'text-on-surface-variant' },
  in_progress: { label: 'In progress', icon: 'progress_activity', tone: 'text-primary' },
  needs_approval: { label: 'Needs approval', icon: 'front_hand', tone: 'text-error' },
  done: { label: 'Done', icon: 'check_circle', tone: 'text-success' },
  failed: { label: 'Failed', icon: 'error', tone: 'text-error' },
}

/** Parse "94.5%" / 12 / "instant" into a 0..1 fraction when it is a percentage. */
export function metricFraction(v: string | number): number | null {
  if (typeof v === 'string' && v.trim().endsWith('%')) {
    const n = parseFloat(v)
    return Number.isFinite(n) ? Math.min(Math.max(n / 100, 0), 1) : null
  }
  return null
}

export const metricLabel = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function KpiBar({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const frac = metricFraction(value)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-on-surface-variant">{metricLabel(label)}</span>
        <span className="font-medium tabular-nums">{typeof value === 'number' ? value.toLocaleString() : value}</span>
      </div>
      {frac !== null && (
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-container-highest">
          <div
            className="h-full rounded-full transition-[width] duration-700"
            style={{ width: `${frac * 100}%`, background: color ?? 'var(--md-primary)' }}
          />
        </div>
      )}
    </div>
  )
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return 'ASAP'
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

export function relativeTime(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.max(s, 0)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}
