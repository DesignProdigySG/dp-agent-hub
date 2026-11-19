import { create } from 'zustand'

import type { ServerMessage } from '../types/contract'
import { emptyHub, reduce, type HubData } from './reduce'

export type View = 'board' | 'calendar' | 'spatial' | 'agents' | 'insights' | 'settings'
export type Theme = 'baseline' | 'dark' | 'forest'
export const THEMES: { id: Theme; label: string }[] = [
  { id: 'baseline', label: 'Baseline' },
  { id: 'dark', label: 'Dark' },
  { id: 'forest', label: 'Forest' },
]

export interface AuthState {
  checked: boolean
  authenticated: boolean
  setupRequired: boolean
  publicRead: boolean
  loginPrompt: boolean // signed-out viewer tried an admin action
}

interface UiState {
  auth: AuthState
  view: View
  theme: Theme
  selectedAgentId: string | null
  editAgentId: string | null // agent open in the Agents editor ('new' for a blank one)
  reviewApprovalId: string | null
  newTask: { open: boolean; agentId?: string; date?: Date }
}

interface Actions {
  setAuth: (auth: Partial<AuthState>) => void
  apply: (msg: ServerMessage) => void
  setConnected: (connected: boolean) => void
  setView: (view: View) => void
  setTheme: (theme: Theme) => void
  selectAgent: (id: string | null) => void
  editAgent: (id: string | null) => void
  review: (approvalId: string | null) => void
  openNewTask: (opts?: { agentId?: string; date?: Date }) => void
  closeNewTask: () => void
}

function loadTheme(): Theme {
  try {
    const t = localStorage.getItem('hub.theme')
    if (t && THEMES.some((x) => x.id === t)) return t as Theme
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'baseline'
}

export const useHub = create<HubData & UiState & Actions>()((set) => ({
  ...emptyHub,
  auth: { checked: false, authenticated: false, setupRequired: false, publicRead: false, loginPrompt: false },
  view: 'board',
  theme: loadTheme(),
  selectedAgentId: null,
  editAgentId: null,
  reviewApprovalId: null,
  newTask: { open: false },

  setAuth: (auth) => set((s) => ({ auth: { ...s.auth, ...auth, checked: true } })),
  apply: (msg) => set((s) => reduce(s, msg)),
  setConnected: (connected) => set({ connected }),
  setView: (view) => set({ view }),
  setTheme: (theme) => {
    try {
      localStorage.setItem('hub.theme', theme)
    } catch {
      /* storage unavailable */
    }
    document.documentElement.dataset.theme = theme // before render, so 3D colors read it
    set({ theme })
  },
  selectAgent: (selectedAgentId) => set({ selectedAgentId }),
  editAgent: (editAgentId) => set({ editAgentId, view: 'agents' }),
  review: (reviewApprovalId) => set({ reviewApprovalId }),
  openNewTask: (opts) => set({ newTask: { open: true, ...opts } }),
  closeNewTask: () => set({ newTask: { open: false } }),
}))

document.documentElement.dataset.theme = useHub.getState().theme
