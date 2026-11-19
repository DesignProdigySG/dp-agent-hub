import { useState, type FormEvent } from 'react'

import { api } from '../lib/api'
import { useHub } from '../store/hub'
import { Dialog, fieldClass } from './Dialog'
import { Button, Icon } from './ui'

function AuthForm() {
  const setupRequired = useHub((s) => s.auth.setupRequired)
  const setAuth = useHub((s) => s.setAuth)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (setupRequired && password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      if (setupRequired) await api.setup(code, password)
      else await api.login(password)
      setAuth({ authenticated: true, setupRequired: false, loginPrompt: false })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {setupRequired ? (
        <>
          <p className="text-sm text-on-surface-variant">
            Create the admin password. For security, enter the one-time <b>setup code</b> printed in the backend log (look for
            “First-run setup code”).
          </p>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-on-surface-variant">Setup code</span>
            <input autoFocus required className={`${fieldClass} font-mono uppercase`} placeholder="XXXX-XXXX-XXXX" value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
        </>
      ) : (
        <p className="text-sm text-on-surface-variant">Sign in with the admin password to manage agents, approvals and settings.</p>
      )}
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-on-surface-variant">{setupRequired ? 'New password (8+ characters)' : 'Password'}</span>
        <input
          autoFocus={!setupRequired}
          required
          type="password"
          autoComplete={setupRequired ? 'new-password' : 'current-password'}
          minLength={setupRequired ? 8 : undefined}
          className={fieldClass}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {setupRequired && (
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-on-surface-variant">Confirm password</span>
          <input required type="password" autoComplete="new-password" className={fieldClass} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </label>
      )}
      {error && <p className="text-sm text-error">{error}</p>}
      <Button type="submit" disabled={busy} className="w-full">
        {setupRequired ? 'Create admin password' : 'Sign in'}
      </Button>
    </form>
  )
}

/** Full-page gate when the hub isn't viewable signed-out; a dialog when it is. */
export function AuthScreen() {
  const auth = useHub((s) => s.auth)
  const setAuth = useHub((s) => s.setAuth)

  if (!auth.checked || auth.authenticated) return null
  if (auth.publicRead && !auth.setupRequired) {
    if (!auth.loginPrompt) return null
    return (
      <Dialog title="Admin sign-in" onClose={() => setAuth({ loginPrompt: false })}>
        <AuthForm />
      </Dialog>
    )
  }
  return (
    <div className="grid min-h-full place-items-center bg-surface p-4">
      <div className="w-full max-w-sm rounded-[28px] bg-surface-container-high p-6 shadow-xl">
        <div className="mb-5 flex items-center gap-2.5">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-on-primary">
            <Icon name="hub" filled />
          </div>
          <div>
            <div className="font-semibold">Marketo Agent Hub</div>
            <div className="text-xs text-on-surface-variant">{auth.setupRequired ? 'First-run setup' : 'Admin sign-in'}</div>
          </div>
        </div>
        <AuthForm />
      </div>
    </div>
  )
}
