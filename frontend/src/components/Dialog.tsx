import { useEffect, type ReactNode } from 'react'

import { Icon } from './ui'

export function Dialog({ title, onClose, children, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal
        onMouseDown={(e) => e.stopPropagation()}
        className={`flex max-h-[90vh] w-full flex-col rounded-[28px] bg-surface-container-high shadow-xl ${wide ? 'max-w-3xl' : 'max-w-lg'}`}
      >
        <header className="flex items-center justify-between px-6 pb-2 pt-5">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="grid h-9 w-9 place-items-center rounded-full hover:bg-on-surface/5" aria-label="Close">
            <Icon name="close" />
          </button>
        </header>
        <div className="min-h-0 overflow-y-auto px-6 pb-6">{children}</div>
      </div>
    </div>
  )
}

export const fieldClass =
  'w-full rounded-xl border border-outline-variant bg-surface px-3 py-2 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary'
