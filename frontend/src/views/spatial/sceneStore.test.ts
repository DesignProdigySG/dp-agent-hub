import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '../../lib/api'
import { DEFAULT_DECOR } from './placement'
import { discardActive, readDraft, useScene } from './sceneStore'

const memory = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (k: string) => memory.get(k) ?? null,
  setItem: (k: string, v: string) => void memory.set(k, v),
  removeItem: (k: string) => void memory.delete(k),
})

const s = () => useScene.getState()

describe('scene editing', () => {
  beforeEach(() => {
    useScene.setState({ pieces: DEFAULT_DECOR, saved: DEFAULT_DECOR, active: null, history: [], status: 'ready', version: 3 })
    s().startEditing()
  })

  it('places new pieces and keeps them in hand', () => {
    s().setColor('blue')
    s().choose('round-hq-brick-2x2')
    s().drop(0, 1, 0)
    s().drop(0, 4, 0)
    expect(s().pieces.slice(-2).map((p) => [p.color, p.y])).toEqual([['blue', 1], ['blue', 4]])
    expect(s().active?.piece).toBe('round-hq-brick-2x2')
    s().undo()
    expect(s().pieces).toHaveLength(DEFAULT_DECOR.length + 1)
  })

  it('moves, puts back and deletes placed pieces', () => {
    const first = DEFAULT_DECOR[0]
    s().pickUp(0)
    expect(s().active?.from).toEqual(first)
    expect(s().pieces).toHaveLength(DEFAULT_DECOR.length - 1)
    s().rotate()
    s().drop(5, 1, 5) // moved and rotated; the hand is empty again
    expect(s().pieces.at(-1)).toMatchObject({ piece: first.piece, x: 5, z: 5, rot: (first.rot + 1) % 4 })
    expect(s().active).toBeNull()

    s().pickUp(0)
    s().release() // Esc: back where it was
    expect(s().pieces).toHaveLength(DEFAULT_DECOR.length)

    s().pickUp(0)
    discardActive() // Delete
    expect(s().pieces).toHaveLength(DEFAULT_DECOR.length - 1)
    s().cancel()
    expect(s().pieces).toEqual(DEFAULT_DECOR)
    expect(s().editing).toBe(false)
  })
})

describe('never overwriting a saved layout', () => {
  const mine = [{ ...DEFAULT_DECOR[0], x: 9 }]
  beforeEach(() => {
    memory.clear()
    useScene.setState({ pieces: DEFAULT_DECOR, saved: DEFAULT_DECOR, editing: false, active: null, history: [], status: 'loading', version: 0, conflict: false, draft: null, error: '' })
  })
  afterEach(() => vi.restoreAllMocks())

  it("can't start editing until the saved layout has loaded, and keeps retrying", async () => {
    vi.useFakeTimers()
    const scene = vi.spyOn(api, 'scene').mockRejectedValueOnce(new Error('backend restarting')).mockResolvedValueOnce({ pieces: mine, version: 7, updated_at: null })
    const loading = s().load()
    s().startEditing()
    expect(s().editing).toBe(false)
    await vi.runAllTimersAsync()
    await loading
    expect(scene).toHaveBeenCalledTimes(2)
    expect(s()).toMatchObject({ status: 'ready', version: 7, pieces: mine })
    s().startEditing()
    expect(s().editing).toBe(true)
    vi.useRealTimers()
  })

  it('saves against the loaded version; a refused save keeps the edits as a draft', async () => {
    useScene.setState({ status: 'ready', version: 4 })
    s().startEditing()
    s().choose('round-hq-brick-2x2')
    s().drop(1, 1, 1)
    expect(readDraft()?.base).toBe(4)
    const save = vi.spyOn(api, 'saveScene').mockRejectedValueOnce(new ApiError(409, 'conflict', { version: 5 }))
    await s().save()
    expect(save).toHaveBeenCalledWith(expect.any(Array), 4)
    expect(s()).toMatchObject({ conflict: true, editing: true })
    expect(readDraft()?.pieces).toHaveLength(DEFAULT_DECOR.length + 1)

    vi.spyOn(api, 'scene').mockResolvedValueOnce({ pieces: mine, version: 5, updated_at: null })
    await s().loadLatest()
    expect(s()).toMatchObject({ editing: false, conflict: false, version: 5, pieces: mine })
    expect(s().draft?.pieces).toHaveLength(DEFAULT_DECOR.length + 1) // offered back
    s().restoreDraft()
    vi.spyOn(api, 'saveScene').mockResolvedValueOnce({ pieces: [], version: 6, updated_at: null })
    await s().save()
    expect(s()).toMatchObject({ editing: false, version: 6 })
    expect(readDraft()).toBeNull()
  })
})
