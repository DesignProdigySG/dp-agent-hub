import { create } from 'zustand'

import { api, type Schedule } from '../lib/api'

/** Recurring schedules (fetched over REST; not part of the live WebSocket snapshot). */
export const useSchedules = create<{ items: Schedule[]; loaded: boolean; load: () => Promise<void> }>()((set) => ({
  items: [],
  loaded: false,
  load: async () => {
    try {
      set({ items: await api.schedules(), loaded: true })
    } catch {
      set({ loaded: true })
    }
  },
}))
