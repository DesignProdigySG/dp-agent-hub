import { describe, expect, it } from 'vitest'

import type { TaskOut } from '../../types/contract'
import { newsFor, thoughtFor } from './thoughts'

const idle = { state: 'IDLE' as const, talking: false, saying: false, news: false }

describe('thought clouds', () => {
  it('shows the most important thought, and none while speaking or idle', () => {
    expect(thoughtFor(idle)).toBeNull()
    expect(thoughtFor({ ...idle, state: 'BUSY' })).toBe('working')
    expect(thoughtFor({ ...idle, state: 'BUSY', talking: true })).toBe('talking')
    expect(thoughtFor({ ...idle, state: 'NEEDS_HELP', talking: true })).toBe('help')
    expect(thoughtFor({ ...idle, state: 'ERROR', news: true })).toBe('error')
    expect(thoughtFor({ ...idle, news: true })).toBe('news')
    expect(thoughtFor({ ...idle, state: 'BUSY', news: true })).toBe('working') // news waits until it's free
    expect(thoughtFor({ ...idle, state: 'NEEDS_HELP', saying: true })).toBeNull() // the speech bubble says it
  })

  it('counts finished tasks since the page opened, until seen', () => {
    const t = (id: string, status: TaskOut['status'], at: string, agent = 'a') => ({ id, agent_id: agent, status, updated_at: at }) as TaskOut
    const tasks = {
      old: t('old', 'done', '2026-01-01T00:00:00Z'),
      fresh: t('fresh', 'done', '2026-06-01T00:00:00Z'),
      running: t('running', 'in_progress', '2026-06-01T00:00:00Z'),
      other: t('other', 'done', '2026-06-01T00:00:00Z', 'b'),
    }
    const opened = Date.parse('2026-03-01T00:00:00Z')
    expect(newsFor('a', tasks, {}, opened)).toEqual(['fresh'])
    expect(newsFor('a', tasks, { fresh: true }, opened)).toEqual([])
  })
})
