import { useEffect, useState } from 'react'

import { Button, Icon } from '../../components/ui'
import { BRICK_COLORS, isLab, labModel, PIECE_INFO, PIECES, piecePreview, SWATCH, type Piece } from './bricks'
import { LAB_GROUPS, LAB_MODELS } from './lab'
import { discardActive, useScene } from './sceneStore'

const GROUPS: { label: string; test: (p: Piece) => boolean }[] = [
  ...LAB_GROUPS.map(({ group, label }) => ({ label, test: (p: Piece) => isLab(p) && LAB_MODELS[labModel(p)][0] === group })),
  { label: 'Bricks', test: (p) => p.startsWith('round-hq-brick') && !p.includes('slope') },
  { label: 'Slopes', test: (p) => p.includes('slope') },
  { label: 'Plates', test: (p) => p.startsWith('round-hq-plate') },
  { label: 'Tiles', test: (p) => p.startsWith('none-hq-plate') },
]

const pieceName = (p: Piece) => {
  if (isLab(p)) return labModel(p).replace(/-/g, ' ')
  const [w, d] = PIECE_INFO[p]
  const kind = p.replace(/^(round|none)-hq-/, '').replace(/-\d+x\d+$/, '').replace(/-/g, ' ')
  return `${kind} ${d}×${w}`
}

const isTyping = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

/** Library, colors and tools for designing the space; shown over the canvas in edit mode. */
export function EditPanel() {
  const { active, color, history, saving, error, pieces, conflict, versions } = useScene()
  const { choose, setColor, rotate, release, undo, save, cancel, resetToDefault, loadLatest, loadVersions, restoreVersion } = useScene.getState()
  const [confirmReset, setConfirmReset] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [confirmRestore, setConfirmRestore] = useState<number | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
      } else if (e.key === 'r' || e.key === 'R') rotate()
      else if (e.key === 'Escape') release()
      else if (e.key === 'Delete' || e.key === 'Backspace') discardActive()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rotate, release, undo])

  return (
    <aside className="pointer-events-auto absolute bottom-3 left-3 top-3 z-30 flex w-72 flex-col overflow-hidden rounded-2xl border border-outline-variant bg-surface/95 shadow-lg backdrop-blur">
      <header className="border-b border-outline-variant px-3 py-2.5">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <Icon name="construction" className="!text-[18px]" /> Design the space
        </h3>
        <p className="mt-0.5 text-xs text-on-surface-variant">
          {active
            ? active.from
              ? 'Click to drop it. R rotates, Esc puts it back, Delete removes it.'
              : 'Click to place (it stays in hand). R rotates, Esc stops.'
            : 'Pick a piece, or click a placed piece to move it. Drag to orbit.'}
        </p>
      </header>

      <div className="border-b border-outline-variant px-3 py-2">
        <div className="mb-1 text-xs font-medium text-on-surface-variant">Color</div>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Brick color">
          {BRICK_COLORS.map((c) => (
            <button
              key={c}
              role="radio"
              aria-checked={color === c}
              aria-label={c}
              title={c}
              onClick={() => setColor(c)}
              className={`h-6 w-6 rounded-md border border-black/10 ${color === c ? 'ring-2 ring-primary ring-offset-1 ring-offset-surface' : ''}`}
              style={{ background: SWATCH[c] }}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2">
        {GROUPS.map((g) => (
          <section key={g.label}>
            <div className="mb-1 text-xs font-medium text-on-surface-variant">{g.label}</div>
            <div className="grid grid-cols-4 gap-1.5">
              {PIECES.filter(g.test).map((p) => (
                <button
                  key={p}
                  onClick={() => choose(p)}
                  title={pieceName(p)}
                  aria-label={pieceName(p)}
                  aria-pressed={active?.piece === p && !active.from}
                  className={`aspect-square rounded-xl p-1 ${active?.piece === p && !active.from ? 'bg-secondary-container ring-2 ring-primary' : 'bg-surface-container hover:bg-surface-container-high'}`}
                >
                  <img src={piecePreview(p)} alt="" draggable={false} className="h-full w-full object-contain" />
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="space-y-2 border-t border-outline-variant px-3 py-2.5">
        <div className="flex flex-wrap gap-1">
          <Button variant="text" onClick={rotate} disabled={!active} title="Rotate (R)">
            <Icon name="rotate_right" /> Rotate
          </Button>
          <Button variant="text" onClick={discardActive} disabled={!active?.from} title="Delete">
            <Icon name="delete" /> Delete
          </Button>
          <Button variant="text" onClick={undo} disabled={!history.length} title="Undo (⌘Z / Ctrl+Z)">
            <Icon name="undo" /> Undo
          </Button>
        </div>
        {confirmReset ? (
          <div className="flex items-center gap-1 text-xs">
            <span className="flex-1">Replace with the default decor?</span>
            <Button variant="text" onClick={() => setConfirmReset(false)}>
              No
            </Button>
            <Button variant="tonal" onClick={() => (resetToDefault(), setConfirmReset(false))}>
              Reset
            </Button>
          </div>
        ) : (
          <Button variant="text" className="w-full" onClick={() => setConfirmReset(true)}>
            <Icon name="restart_alt" /> Reset to default
          </Button>
        )}
        <Button variant="text" className="w-full" onClick={() => (setShowVersions(!showVersions), loadVersions())}>
          <Icon name="history" /> Earlier versions
        </Button>
        {showVersions && (
          <ul className="max-h-40 space-y-1 overflow-y-auto text-xs">
            {!versions.length && <li className="text-on-surface-variant">No earlier versions yet.</li>}
            {versions.map((v) => (
              <li key={v.id} className="flex items-center gap-2">
                <span className="flex-1">
                  v{v.version} · {v.pieces || 'default'} pieces · {new Date(v.saved_at).toLocaleString()}
                </span>
                {confirmRestore === v.id ? (
                  <Button variant="tonal" className="!h-7 !px-2" onClick={() => (restoreVersion(v.id), setConfirmRestore(null))}>Restore</Button>
                ) : (
                  <Button variant="text" className="!h-7 !px-2" onClick={() => setConfirmRestore(v.id)}>Use</Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {error && <p className="text-xs text-error">{error}</p>}
        {conflict && (
          <Button variant="tonal" className="w-full" onClick={loadLatest}>
            <Icon name="sync" /> Load the latest layout
          </Button>
        )}
        <div className="flex gap-2">
          <Button variant="text" className="flex-1" onClick={cancel} disabled={saving}>
            Cancel
          </Button>
          <Button className="flex-1" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : `Save · ${pieces.length}`}
          </Button>
        </div>
      </div>
    </aside>
  )
}
