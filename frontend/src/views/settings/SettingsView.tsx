import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'

import { fieldClass } from '../../components/Dialog'
import { Button, Icon, relativeTime } from '../../components/ui'
import { api, ApiError, type ConfigField, type ConfigResponse, type TestResult } from '../../lib/api'
import { THEMES, useHub } from '../../store/hub'

type Draft = Record<string, unknown>
const TESTS: Record<string, 'marketo' | 'llm' | 'datastreams' | 'datalake' | 'email'> = {
  marketo: 'marketo',
  llm: 'llm',
  activities: 'datastreams',
  datalake: 'datalake',
  email: 'email',
}
const SOURCE_LABEL = { ui: 'Saved here', env: 'From .env', default: 'Default' }

function Card({ title, icon, description, actions, children }: { title: string; icon: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-3xl bg-surface-container p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
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

function TestOutcome({ result }: { result: TestResult }) {
  const rows: { label: string; ok: boolean; text: string }[] = []
  if (result.rest) rows.push({ label: 'REST', ok: result.rest.ok, text: result.rest.detail ?? result.rest.error ?? '' })
  if (result.mcp) rows.push({ label: 'MCP', ok: result.mcp.ok, text: result.mcp.detail ?? result.mcp.error ?? '' })
  for (const r of result.results ?? []) rows.push({ label: r.model, ok: r.ok, text: r.ok ? `replied in ${r.latency_ms} ms` : (r.error ?? '') })
  if (!rows.length) rows.push({ label: result.ok ? 'OK' : 'Failed', ok: result.ok, text: result.detail ?? result.error ?? '' })
  return (
    <ul className="mt-3 space-y-1 rounded-2xl bg-surface p-3 text-xs">
      {rows.map((r) => (
        <li key={r.label} className="flex gap-2">
          <Icon name={r.ok ? 'check_circle' : 'error'} filled className={`!text-[16px] ${r.ok ? 'text-success' : 'text-error'}`} />
          <span className="font-medium">{r.label}</span>
          <span className="text-on-surface-variant">{r.text}</span>
        </li>
      ))}
    </ul>
  )
}

function SecretInput({ field, draft, setDraft }: { field: ConfigField; draft: Draft; setDraft: (k: string, v: unknown) => void }) {
  const pending = field.key in draft
  const [editing, setEditing] = useState(false)
  if (editing || (pending && draft[field.key] !== null)) {
    return (
      <div className="flex gap-2">
        <input
          type="password"
          aria-label={field.label}
          autoComplete="off"
          autoFocus={editing}
          className={fieldClass}
          placeholder="Enter new value"
          value={(draft[field.key] as string) ?? ''}
          onChange={(e) => setDraft(field.key, e.target.value)}
        />
        <Button
          variant="text"
          onClick={() => {
            setEditing(false)
            setDraft(field.key, undefined)
          }}
        >
          Cancel
        </Button>
      </div>
    )
  }
  const cleared = pending && draft[field.key] === null
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`flex-1 rounded-xl border border-dashed border-outline-variant px-3 py-2 ${field.is_set && !cleared ? '' : 'text-on-surface-variant'}`}>
        {cleared ? 'Will be cleared' : field.is_set ? `Set ${field.hint ?? ''}` : 'Not set'}
      </span>
      <Button variant="tonal" onClick={() => setEditing(true)}>
        {field.is_set ? 'Replace' : 'Set'}
      </Button>
      {field.is_set && !cleared && field.source === 'ui' && (
        <Button variant="text" onClick={() => setDraft(field.key, null)} title="Remove the stored secret">
          Clear
        </Button>
      )}
    </div>
  )
}

function FieldInput({ field, draft, setDraft }: { field: ConfigField; draft: Draft; setDraft: (k: string, v: unknown) => void }) {
  const value = field.key in draft && draft[field.key] !== null ? draft[field.key] : field.value
  if (field.kind === 'secret') return <SecretInput field={field} draft={draft} setDraft={setDraft} />
  if (field.kind === 'bool') {
    const on = Boolean(value)
    return (
      <button
        type="button"
        role="switch"
        aria-label={field.label}
        aria-checked={on}
        onClick={() => setDraft(field.key, !on)}
        className={`relative h-7 w-12 rounded-full transition ${on ? 'bg-primary' : 'bg-surface-container-highest ring-1 ring-outline'}`}
      >
        <span className={`absolute top-1 h-5 w-5 rounded-full transition-all ${on ? 'left-6 bg-on-primary' : 'left-1 bg-outline'}`} />
      </button>
    )
  }
  if (field.kind === 'select') {
    return (
      <select aria-label={field.label} className={fieldClass} value={String(value ?? '')} onChange={(e) => setDraft(field.key, e.target.value)}>
        {field.options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      aria-label={field.label}
      className={`${fieldClass} ${field.kind === 'number' ? 'tabular-nums' : ''}`}
      type={field.kind === 'number' ? 'number' : 'text'}
      step="any"
      placeholder={field.placeholder}
      value={String(value ?? '')}
      onChange={(e) => setDraft(field.key, field.kind === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)}
    />
  )
}

function StatusPanel({ status }: { status: ConfigResponse['status'] }) {
  const ing = status.ingestion
  return (
    <Card title="Status" icon="monitor_heart">
      <div className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <div className="flex justify-between">
          <span className="text-on-surface-variant">Database</span>
          <span className="font-medium">{status.database === 'postgres' ? 'Postgres' : 'SQLite (dev)'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-on-surface-variant">Activity source</span>
          <span className="font-medium">{ing.source}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-on-surface-variant">Last poll</span>
          <span className="font-medium">{ing.last_poll_at ? `${relativeTime(ing.last_poll_at)} · +${ing.last_count}` : '—'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-on-surface-variant">Data Lake</span>
          <span className="font-medium">{ing.lake.enabled ? (ing.lake.last_error ? 'Error' : 'Archiving') : 'Off'}</span>
        </div>
      </div>
      <div className="mt-3 space-y-1 border-t border-outline-variant pt-3 text-sm">
        <div className="text-xs font-medium text-on-surface-variant">LLM routes</div>
        {(['fast', 'standard', 'strong'] as const).map((t) => (
          <div key={t} className="flex items-baseline gap-3">
            <span className="w-20 shrink-0 capitalize text-on-surface-variant">{t}</span>
            <span className="min-w-0 break-all font-mono text-xs">{status.routes[t]?.blocked || status.routes[t]?.models.join(' → ')}</span>
          </div>
        ))}
      </div>
      {[status.marketo_error, ing.last_error, ing.lake.last_error].filter(Boolean).map((e) => (
        <p key={e} className="mt-3 rounded-xl bg-error-container px-3 py-2 text-xs text-error">
          {e}
        </p>
      ))}
    </Card>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.changePassword(current, next)
      setCurrent('')
      setNext('')
      setMsg({ ok: true, text: 'Password changed. Other sessions were signed out.' })
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message })
    }
  }
  return (
    <Card title="Admin password" icon="key">
      <form onSubmit={submit} className="space-y-3">
        <input type="password" autoComplete="current-password" required className={fieldClass} placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <input type="password" autoComplete="new-password" required minLength={8} className={fieldClass} placeholder="New password (8+ characters)" value={next} onChange={(e) => setNext(e.target.value)} />
        <div className="flex items-center justify-between gap-2">
          <span className={`text-xs ${msg?.ok ? 'text-success' : 'text-error'}`}>{msg?.text}</span>
          <Button type="submit">Change password</Button>
        </div>
      </form>
    </Card>
  )
}

function ThemeCard() {
  const theme = useHub((s) => s.theme)
  const setTheme = useHub((s) => s.setTheme)
  return (
    <Card title="Theme" icon="palette" description="Themes swap the shell and the 3D scene together. This choice is saved in this browser only.">
      <div className="flex flex-wrap gap-2">
        {THEMES.map((t) => (
          <button
            key={t.id}
            onClick={() => setTheme(t.id)}
            data-theme={t.id}
            className={`flex items-center gap-2 rounded-2xl border bg-surface px-3 py-2 text-sm text-on-surface ${theme === t.id ? 'border-2 border-primary' : 'border-outline-variant'}`}
          >
            <span className="flex">
              {['--md-primary', '--zone-database', '--zone-campaigns', '--zone-design_studio'].map((v) => (
                <span key={v} className="-mr-1 h-4 w-4 rounded-full border border-surface" style={{ background: `var(${v})` }} />
              ))}
            </span>
            <span className="ml-1">{t.label}</span>
          </button>
        ))}
      </div>
    </Card>
  )
}

export function SettingsView() {
  const authenticated = useHub((s) => s.auth.authenticated)
  const setAuth = useHub((s) => s.setAuth)
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [draft, setDraftState] = useState<Draft>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [tests, setTests] = useState<Record<string, TestResult | 'running'>>({})

  useEffect(() => {
    if (!authenticated) return
    api.getConfig().then(setConfig).catch((e: Error) => setNotice(e.message))
  }, [authenticated])

  const setDraft = (key: string, value: unknown) =>
    setDraftState((d) => {
      const next = { ...d }
      if (value === undefined) delete next[key]
      else next[key] = value
      return next
    })

  const byGroup = useMemo(() => {
    const m = new Map<string, ConfigField[]>()
    for (const f of config?.fields ?? []) m.set(f.group, [...(m.get(f.group) ?? []), f])
    return m
  }, [config])

  if (!authenticated) {
    return (
      <div className="grid h-full content-start gap-3 overflow-y-auto lg:grid-cols-2">
        <ThemeCard />
        <Card title="Hub settings" icon="lock" description="Sign in as admin to view and change connections, credentials and the LLM router.">
          <Button onClick={() => setAuth({ loginPrompt: true })}>
            <Icon name="login" /> Sign in
          </Button>
        </Card>
      </div>
    )
  }

  const save = async () => {
    setSaving(true)
    setErrors({})
    try {
      const changes = Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== ''))
      setConfig(await api.updateConfig(changes))
      setDraftState({})
      setNotice('Saved. Changes are live — no restart needed.')
    } catch (e) {
      const detail = e instanceof ApiError ? (e.detail as { errors?: Record<string, string> }) : undefined
      if (detail?.errors) setErrors(detail.errors)
      setNotice((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const runTest = async (group: string) => {
    setTests((t) => ({ ...t, [group]: 'running' }))
    try {
      const result = await api.testConnection(TESTS[group])
      setTests((t) => ({ ...t, [group]: result }))
    } catch (e) {
      setTests((t) => ({ ...t, [group]: { ok: false, error: (e as Error).message } }))
    }
  }

  const dirty = Object.keys(draft).length

  return (
    <div className="relative h-full overflow-y-auto">
      <div className="grid content-start gap-3 pb-20 xl:grid-cols-2">
        {config && <StatusPanel status={config.status} />}
        <ThemeCard />
        {!config && <p className="p-4 text-sm text-on-surface-variant">{notice ?? 'Loading settings...'}</p>}
        {config?.groups.map((g) => {
          const fields = byGroup.get(g.id) ?? []
          const test = tests[g.id]
          return (
            <Card
              key={g.id}
              title={g.label}
              icon={{ access: 'shield_person', marketo: 'hub', llm: 'psychology', activities: 'stream', datalake: 'database', notifications: 'notifications_active', email: 'mail', verification: 'verified', governor: 'speed', operations: 'tune' }[g.id] ?? 'settings'}
              description={g.description}
              actions={
                TESTS[g.id] && (
                  <Button variant="tonal" disabled={test === 'running' || dirty > 0} onClick={() => runTest(g.id)} title={dirty ? 'Save changes before testing' : 'Test with the saved settings'}>
                    <Icon name={test === 'running' ? 'progress_activity' : 'lan'} className={test === 'running' ? 'animate-spin' : ''} /> Test
                  </Button>
                )
              }
            >
              <div className="space-y-4">
                {fields.map((f) => (
                  <div key={f.key}>
                    <span className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-on-surface-variant">{f.label}</span>
                      <span className="flex items-center gap-1">
                        <span className={`rounded px-1.5 text-[10px] ${f.key in draft ? 'bg-primary-container text-on-primary-container' : 'text-on-surface-variant'}`}>
                          {f.key in draft ? 'Unsaved' : SOURCE_LABEL[f.source]}
                        </span>
                        {f.source === 'ui' && f.kind !== 'secret' && !(f.key in draft) && (
                          <button type="button" className="text-[10px] text-primary" onClick={() => setDraft(f.key, null)} title="Remove the saved value and fall back to .env / default">
                            Reset
                          </button>
                        )}
                      </span>
                    </span>
                    <FieldInput field={f} draft={draft} setDraft={setDraft} />
                    {errors[f.key] ? <span className="mt-1 block text-xs text-error">{errors[f.key]}</span> : f.help && <span className="mt-1 block text-xs text-on-surface-variant">{f.help}</span>}
                  </div>
                ))}
              </div>
              {test && test !== 'running' && <TestOutcome result={test} />}
            </Card>
          )
        })}
        {config && <PasswordCard />}
      </div>
      {(dirty > 0 || notice) && config && (
        <div className="sticky bottom-0 flex items-center justify-between gap-3 rounded-2xl bg-surface-container-highest px-4 py-3 shadow-lg">
          <span className="text-sm">{dirty > 0 ? `${dirty} unsaved change${dirty > 1 ? 's' : ''}` : notice}</span>
          <span className="flex gap-2">
            {dirty > 0 ? (
              <>
                <Button
                  variant="text"
                  onClick={() => {
                    setDraftState({})
                    setErrors({})
                  }}
                >
                  Discard
                </Button>
                <Button disabled={saving} onClick={save}>
                  Save
                </Button>
              </>
            ) : (
              <Button variant="text" onClick={() => setNotice(null)}>
                Dismiss
              </Button>
            )}
          </span>
        </div>
      )}
    </div>
  )
}
