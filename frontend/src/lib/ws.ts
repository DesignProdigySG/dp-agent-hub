import { useHub } from '../store/hub'
import type { ServerMessage } from '../types/contract'
import { onAgentEvent, placeAll, setAgentOrder } from '../views/spatial/motion'

/** Connect to the hub event stream, reconnecting with backoff. Returns a disposer. */
export function connectHub(): () => void {
  let ws: WebSocket | null = null
  let retry = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let ping: ReturnType<typeof setInterval> | undefined
  let closed = false

  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws`)
    ws.onopen = () => {
      retry = 0
      useHub.getState().setConnected(true)
      ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25_000)
    }
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data) as ServerMessage
      if (msg.type === 'snapshot') {
        setAgentOrder(msg.agents.map((a) => a.id))
        placeAll(msg.statuses)
      } else if (msg.type === 'agent_event') {
        onAgentEvent(msg)
      }
      useHub.getState().apply(msg)
    }
    ws.onclose = (e) => {
      clearInterval(ping)
      if (closed) return
      useHub.getState().setConnected(false)
      if (e.code === 4401) {
        // Session expired or signed out elsewhere: show sign-in instead of retrying.
        useHub.getState().setAuth({ authenticated: false })
        return
      }
      timer = setTimeout(open, Math.min(1000 * 2 ** retry++, 15_000))
    }
  }

  open()
  return () => {
    closed = true
    clearTimeout(timer)
    clearInterval(ping)
    if (ws) {
      // Detach first: a disposed socket (e.g. StrictMode's first mount) must never touch
      // shared state, or its late close/message events clobber the live connection.
      ws.onopen = ws.onmessage = ws.onclose = null
      ws.close()
    }
  }
}
