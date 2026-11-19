import type { ReactNode } from 'react'

import type { MarketoChange } from '../lib/api'
import { Icon } from './ui'

/** A link that opens in Marketo (new tab). */
export function MarketoLink({ href, children, className = '' }: { href: string; children?: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex items-center gap-0.5 text-primary hover:underline ${className}`}>
      {children ?? 'Open in Marketo'}
      <Icon name="open_in_new" className="!text-[14px]" />
    </a>
  )
}

/** What a task or agent created or changed in Marketo, each linked when it can be. */
export function MarketoChanges({ changes, linksConfigured = true, title = 'In Marketo' }: { changes: MarketoChange[]; linksConfigured?: boolean; title?: string }) {
  if (!changes.length) return null
  return (
    <section className="rounded-2xl bg-surface-container p-3">
      <h3 className="mb-1.5 flex items-center gap-1 text-sm font-semibold">
        <Icon name="hub" className="!text-[18px]" /> {title}
      </h3>
      <ul className="space-y-1 text-sm">
        {changes.map((c) => (
          <li key={c.id} className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-on-surface-variant">{c.action}</span>
            {c.url ? (
              <MarketoLink href={c.url}>
                {c.label} {c.name ? `“${c.name}”` : c.object_id}
              </MarketoLink>
            ) : (
              <span>
                {c.label} {c.name ? `“${c.name}”` : ''} <span className="text-xs text-on-surface-variant">(ID {c.object_id})</span>
              </span>
            )}
            {c.detail && <span className="text-xs text-on-surface-variant">{c.detail}</span>}
          </li>
        ))}
      </ul>
      {!linksConfigured && <p className="mt-1.5 text-xs text-on-surface-variant">Add Settings › Marketo › “Marketo address for links” to open these in Marketo.</p>}
    </section>
  )
}
