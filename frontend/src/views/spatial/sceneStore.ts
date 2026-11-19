/**
 * Spatial edit mode state: the decor layout, what's under the cursor, and undo.
 *
 * The "active" piece follows the pointer: a new piece picked from the library, or a placed
 * piece the user picked up. Clicking drops it; Esc puts a picked-up piece back.
 *
 * Nothing can overwrite a saved layout by accident: editing only starts once the layout has
 * loaded (loading retries until it does), every save names the version it was edited from
 * and the server refuses it if the layout changed since, unsaved edits are kept as a draft
 * in this browser, and the store survives hot reloads during development.
 */
import { create } from 'zustand'

import { api, ApiError, type SceneVersion } from '../../lib/api'
import type { BrickColor, Piece } from './bricks'
import { DEFAULT_DECOR, sanitize, type Placed } from './placement'

export interface Active {
  piece: Piece
  color: BrickColor
  rot: Placed['rot']
  from: Placed | null // where a picked-up piece came from
}

export interface Draft {
  pieces: Placed[]
  base: number // the version the edits started from
  at: string
}

interface SceneState {
  pieces: Placed[]
  saved: Placed[] // what the server holds (or the default)
  isDefault: boolean
  status: 'loading' | 'ready' | 'error'
  version: number // the saved layout's version these pieces came from
  conflict: boolean // the last save was refused: the layout changed elsewhere
  draft: Draft | null // unsaved edits found from an earlier session
  versions: SceneVersion[]
  editing: boolean
  active: Active | null
  color: BrickColor
  history: Placed[][]
  saving: boolean
  error: string
  load: () => Promise<void>
  loadLatest: () => Promise<void>
  restoreDraft: () => void
  discardDraft: () => void
  loadVersions: () => Promise<void>
  restoreVersion: (id: number) => Promise<void>
  startEditing: () => void
  cancel: () => void
  save: () => Promise<void>
  resetToDefault: () => void
  choose: (piece: Piece) => void
  setColor: (color: BrickColor) => void
  rotate: () => void
  pickUp: (index: number) => void
  drop: (x: number, y: number, z: number) => void
  release: () => void
  undo: () => void
}

const same = (a: Placed[], b: Placed[]) => JSON.stringify(a) === JSON.stringify(b)

const DRAFT_KEY = 'hub.scene.draft'
export function readDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch {
    return null
  }
}
export function writeDraft(d: Draft | null) {
  try {
    if (d) localStorage.setItem(DRAFT_KEY, JSON.stringify(d))
    else localStorage.removeItem(DRAFT_KEY)
  } catch {
    /* private window / blocked storage: no draft */
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const createScene = () => create<SceneState>()((set, get) => {
  const commit = (pieces: Placed[]) => set((s) => ({ pieces, history: [...s.history.slice(-49), s.pieces] }))
  const apply = (layout: { pieces: Placed[] | null; version: number }) => {
    const pieces = layout.pieces ? sanitize(layout.pieces) : DEFAULT_DECOR
    set({ pieces, saved: pieces, isDefault: layout.pieces === null, version: layout.version, status: 'ready', conflict: false })
  }
  return {
    pieces: DEFAULT_DECOR,
    saved: DEFAULT_DECOR,
    isDefault: true,
    status: 'loading',
    version: 0,
    conflict: false,
    draft: null,
    versions: [],
    editing: false,
    active: null,
    color: 'red',
    history: [],
    saving: false,
    error: '',

    load: async () => {
      // Keep trying: showing the default decor because a request failed (e.g. while the
      // backend restarts) is what let a stale page save over a real layout.
      for (let attempt = 0; ; attempt++) {
        try {
          const layout = await api.scene()
          if (!get().editing) apply(layout as { pieces: Placed[] | null; version: number })
          const draft = readDraft()
          set({ draft: draft && !same(draft.pieces, get().saved) ? draft : null })
          return
        } catch (e) {
          if (e instanceof ApiError && e.status === 401) return set({ status: 'error', error: 'Sign in to see the layout.' })
          set({ status: get().status === 'ready' ? 'ready' : 'error' })
          await sleep(Math.min(1000 * 2 ** attempt, 15000))
        }
      }
    },
    loadLatest: async () => {
      const layout = await api.scene()
      set({ editing: false, active: null, history: [], error: '' }) // before the swap: keeps the draft
      apply(layout as { pieces: Placed[] | null; version: number })
      set({ draft: readDraft() })
    },
    restoreDraft: () => {
      const { draft, status } = get()
      if (!draft || status !== 'ready') return
      set({ editing: true, active: null, error: '', draft: null })
      commit(draft.pieces)
    },
    discardDraft: () => {
      writeDraft(null)
      set({ draft: null })
    },
    loadVersions: async () => set({ versions: await api.sceneHistory() }),
    restoreVersion: async (id) => {
      set({ saving: true, error: '' })
      try {
        apply((await api.restoreScene(id, get().version)) as { pieces: Placed[] | null; version: number })
        writeDraft(null)
        set({ saving: false, editing: false, active: null, history: [], draft: null, versions: await api.sceneHistory() })
      } catch (e) {
        const conflict = e instanceof ApiError && e.status === 409
        set({ saving: false, conflict, error: conflict ? 'The layout changed elsewhere. Load the latest first.' : (e as Error).message })
      }
    },
    startEditing: () => {
      if (get().status !== 'ready') return
      set({ editing: true, active: null, history: [], error: '', conflict: false })
    },
    cancel: () => {
      writeDraft(null)
      set((s) => ({ editing: false, active: null, pieces: s.saved, history: [], error: '', conflict: false }))
    },
    save: async () => {
      const { pieces, version } = get()
      set({ saving: true, error: '' })
      try {
        const asDefault = same(pieces, DEFAULT_DECOR)
        const out = await api.saveScene(asDefault ? null : pieces, version)
        writeDraft(null)
        set({ saved: pieces, isDefault: asDefault, version: out.version, editing: false, active: null, history: [], saving: false, conflict: false })
      } catch (e) {
        const conflict = e instanceof ApiError && e.status === 409
        set({
          saving: false,
          conflict,
          error: conflict ? 'Not saved: the layout was changed somewhere else since you loaded it. Your edits are kept as a draft.' : (e as Error).message,
        })
      }
    },
    resetToDefault: () => {
      commit(DEFAULT_DECOR)
      set({ active: null })
    },
    choose: (piece) => set((s) => ({ active: { piece, color: s.color, rot: s.active?.rot ?? 0, from: null } })),
    setColor: (color) => set((s) => ({ color, active: s.active && { ...s.active, color } })),
    rotate: () => set((s) => ({ active: s.active && { ...s.active, rot: ((s.active.rot + 1) % 4) as Placed['rot'] } })),
    pickUp: (index) => {
      const s = get()
      const p = s.pieces[index]
      if (!p || s.active) return
      commit(s.pieces.filter((_, i) => i !== index))
      set({ active: { piece: p.piece, color: p.color, rot: p.rot, from: p }, color: p.color })
    },
    drop: (x, y, z) => {
      const { active, pieces } = get()
      if (!active) return
      commit([...pieces, { piece: active.piece, color: active.color, x, y, z, rot: active.rot }])
      // a moved piece is done; a new piece stays in hand so you can keep placing it
      if (active.from) set({ active: null })
    },
    release: () => {
      const { active, pieces } = get()
      if (active?.from) set({ pieces: [...pieces, active.from] })
      set({ active: null })
    },
    undo: () => {
      const { history } = get()
      if (!history.length) return
      set({ pieces: history[history.length - 1], history: history.slice(0, -1), active: null })
    },
  }
})

function init() {
  const store = createScene()
  // While editing, every change is kept as a draft in this browser.
  store.subscribe((s, prev) => {
    if (s.editing && s.pieces !== prev.pieces) writeDraft({ pieces: s.pieces, base: s.version, at: new Date().toISOString() })
  })
  return store
}

// Keep the same store across hot reloads, so editing code never swaps a loaded layout for
// the default decor in an open tab.
export const useScene: ReturnType<typeof createScene> = import.meta.hot?.data.scene ?? init()
if (import.meta.hot) import.meta.hot.data.scene = useScene
/** Discard a picked-up piece (it was already removed from the layout when picked up). */
export const discardActive = () => useScene.setState({ active: null })
