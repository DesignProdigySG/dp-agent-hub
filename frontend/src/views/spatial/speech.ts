/**
 * What agents are saying right now (speech bubbles), and who's in a conversation (the
 * listener's thought cloud). Fed each frame from the conversations in motion.ts; the store
 * only changes when they do.
 */
import { create } from 'zustand'

interface SpeechState {
  lines: Record<string, string>
  talking: string[]
  setLines: (lines: Record<string, string>, talking?: string[]) => void
}

export const useSpeech = create<SpeechState>()((set, get) => ({
  lines: {},
  talking: [],
  setLines: (lines, talking = []) => {
    const prev = get()
    const keys = Object.keys(lines)
    const sameLines = keys.length === Object.keys(prev.lines).length && keys.every((k) => prev.lines[k] === lines[k])
    const sameTalking = talking.length === prev.talking.length && talking.every((id, i) => prev.talking[i] === id)
    if (sameLines && sameTalking) return
    set({ lines, talking })
  },
}))
