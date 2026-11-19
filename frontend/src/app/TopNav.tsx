import { Icon } from '../components/ui'
import { api } from '../lib/api'
import { useHub } from '../store/hub'

function GovernorMeter() {
  const g = useHub((s) => s.governor)
  if (!g) return null
  const frac = g.calls_in_window / g.window_limit
  const tone = frac > 0.85 ? 'var(--md-error)' : frac > 0.6 ? 'var(--md-warning)' : 'var(--md-success)'
  return (
    <div
      className="hidden items-center gap-2 rounded-full bg-surface-container px-3 py-1.5 text-xs md:flex"
      title={`Marketo rate governor (REST + MCP share one budget)\nIn flight ${g.in_flight}/${g.max_concurrent} · queued ${g.queued}\nDaily ${g.daily_used.toLocaleString()} / ${g.daily_quota.toLocaleString()}\nREST ${g.by_channel.rest ?? 0} · MCP ${g.by_channel.mcp ?? 0}`}
    >
      <Icon name="speed" className="!text-[18px] text-on-surface-variant" />
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-container-highest">
        <div className="h-full rounded-full transition-[width]" style={{ width: `${Math.min(frac, 1) * 100}%`, background: tone }} />
      </div>
      <span className="tabular-nums text-on-surface-variant">
        {g.calls_in_window}/{g.window_limit} per {g.window_s}s
      </span>
      {g.queued > 0 && <span className="font-medium text-warning">{g.queued} queued</span>}
    </div>
  )
}

function AccountButton() {
  const auth = useHub((s) => s.auth)
  const setAuth = useHub((s) => s.setAuth)
  if (!auth.authenticated) {
    return (
      <button onClick={() => setAuth({ loginPrompt: true })} className="flex h-9 items-center gap-1 rounded-full px-3 text-sm text-primary hover:bg-primary/10">
        <Icon name="login" /> Sign in
      </button>
    )
  }
  const signOut = async () => {
    await api.logout().catch(() => undefined)
    setAuth({ authenticated: false })
  }
  return (
    <button onClick={signOut} title="Sign out" className="grid h-10 w-10 place-items-center rounded-full hover:bg-on-surface/5">
      <Icon name="logout" />
    </button>
  )
}

export function TopNav() {
  const connected = useHub((s) => s.connected)
  const mode = useHub((s) => s.mode)
  const approvals = useHub((s) => s.approvals)
  const pending = Object.values(approvals).filter((a) => a.status === 'pending')

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 px-4">
      <div className="flex items-center gap-2.5">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-primary text-on-primary">
          <Icon name="hub" filled />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold">Marketo Agent Hub</div>
          <div className="text-[11px] text-on-surface-variant">Operations console</div>
        </div>
      </div>
      {mode && (
        <span
          className={`ml-2 rounded-lg px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
            mode === 'live' ? 'bg-error-container text-error' : 'bg-secondary-container text-on-secondary-container'
          }`}
          title={mode === 'demo' ? 'Agents run against an in-memory Marketo sandbox' : 'Agents are connected to a real Marketo instance'}
        >
          {mode === 'demo' ? 'Demo sandbox' : 'Live Marketo'}
        </span>
      )}
      <div className="flex-1" />
      <GovernorMeter />
      <button
        onClick={() => pending[0] && useHub.getState().review(pending[0].id)}
        className="relative grid h-10 w-10 place-items-center rounded-full hover:bg-on-surface/5"
        title={pending.length ? `${pending.length} approval(s) waiting` : 'No approvals waiting'}
      >
        <Icon name="notifications" filled={pending.length > 0} />
        {pending.length > 0 && (
          <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-error px-1 text-[10px] font-bold text-on-error">
            {pending.length}
          </span>
        )}
      </button>
      <span
        className={`flex items-center gap-1.5 text-xs ${connected ? 'text-success' : 'text-error'}`}
        title={connected ? 'Live event stream connected' : 'Reconnecting to backend...'}
      >
        <span className={`h-2 w-2 rounded-full ${connected ? 'bg-success' : 'bg-error'}`} />
        <span className="hidden sm:inline">{connected ? 'Live' : 'Offline'}</span>
      </span>
      <AccountButton />
    </header>
  )
}
