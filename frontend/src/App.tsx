import { lazy, Suspense, useEffect } from 'react'

import { AgentProfileSidebar } from './app/AgentProfileSidebar'
import { LeftSidebar } from './app/LeftSidebar'
import { TopNav } from './app/TopNav'
import { ApprovalModal } from './components/ApprovalModal'
import { AuthScreen } from './components/AuthScreen'
import { api, setUnauthorizedHandler } from './lib/api'
import { connectHub } from './lib/ws'
import { useHub } from './store/hub'
import { NewTaskDialog } from './views/board/NewTaskDialog'
import { TaskBoard } from './views/board/TaskBoard'
import { CalendarView } from './views/calendar/CalendarView'
import { SettingsView } from './views/settings/SettingsView'

const SpatialView = lazy(() => import('./views/spatial/SpatialView'))
const InsightsView = lazy(() => import('./views/insights/InsightsView'))
const AgentsView = lazy(() => import('./views/agents/AgentsView'))

const VIEWS = { board: TaskBoard, calendar: CalendarView, spatial: SpatialView, agents: AgentsView, insights: InsightsView, settings: SettingsView }

function useAuthCheck() {
  const setAuth = useHub((s) => s.setAuth)
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const check = () =>
      api
        .me()
        .then((m) => setAuth({ authenticated: m.authenticated, setupRequired: m.setup_required, publicRead: m.public_read_access }))
        .catch(() => (timer = setTimeout(check, 3000))) // backend not up yet
    check()
    setUnauthorizedHandler(() => {
      const { auth } = useHub.getState()
      setAuth(auth.publicRead ? { authenticated: false, loginPrompt: true } : { authenticated: false })
    })
    return () => clearTimeout(timer)
  }, [setAuth])
}

/** "Review in the hub" links in notification emails open /?approval=<id>: show it once loaded. */
function useApprovalDeepLink(ready: boolean) {
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('approval')
    if (!ready || !id) return
    const ui = useHub.getState()
    ui.setView('board')
    ui.review(id)
    const url = new URL(window.location.href)
    url.searchParams.delete('approval')
    window.history.replaceState(null, '', url)
  }, [ready])
}

export default function App() {
  const view = useHub((s) => s.view)
  const connected = useHub((s) => s.connected)
  const hasData = useHub((s) => s.loaded)
  const auth = useHub((s) => s.auth)
  useAuthCheck()
  const canView = auth.authenticated || (auth.publicRead && !auth.setupRequired)
  useEffect(() => (canView ? connectHub() : undefined), [canView, auth.authenticated])
  useApprovalDeepLink(hasData)
  const View = VIEWS[view]

  if (!auth.checked) {
    return <div className="grid h-full place-items-center text-sm text-on-surface-variant">Connecting to the agent hub backend...</div>
  }
  if (!canView) return <AuthScreen />

  return (
    <div className="flex h-full flex-col bg-surface text-on-surface">
      <TopNav />
      <div className="flex min-h-0 flex-1 gap-3 pb-3 pr-3">
        <LeftSidebar />
        <main className="min-h-0 min-w-0 flex-1">
          {hasData ? (
            <Suspense fallback={<div className="h-full rounded-3xl bg-surface-container" />}>
              <View />
            </Suspense>
          ) : (
            <div className="grid h-full place-items-center rounded-3xl bg-surface-container text-sm text-on-surface-variant">
              {connected ? 'Loading hub...' : 'Connecting to the agent hub backend...'}
            </div>
          )}
        </main>
        <AgentProfileSidebar />
      </div>
      <NewTaskDialog />
      <ApprovalModal />
      <AuthScreen />
    </div>
  )
}
