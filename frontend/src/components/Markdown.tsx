/**
 * Agents write Markdown (headings, lists, tables, links to Marketo); this renders it, styled
 * for the hub. No raw HTML: react-markdown skips it, and its default URL check drops unsafe
 * links (javascript: and the like). Links open in a new tab.
 */
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Icon } from './ui'

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-baseline gap-0.5 text-primary underline-offset-2 hover:underline">
      {children}
      {href?.includes('marketo') && <Icon name="open_in_new" className="!text-[12px]" />}
    </a>
  ),
  h1: ({ children }) => <h3 className="mb-1 mt-3 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h4 className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h4>,
  h3: ({ children }) => <h5 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h5>,
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  code: ({ children }) => <code className="rounded bg-surface-container-highest px-1 py-0.5 text-[0.85em]">{children}</code>,
  pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-xl bg-surface-container-highest p-2 text-xs">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-outline-variant pl-3 text-on-surface-variant">{children}</blockquote>,
  hr: () => <hr className="my-3 border-outline-variant" />,
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded-xl border border-outline-variant">
      <table className="w-full text-left text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-container-highest">{children}</thead>,
  th: ({ children }) => <th className="px-2 py-1.5 font-medium">{children}</th>,
  td: ({ children }) => <td className="border-t border-outline-variant px-2 py-1 align-top">{children}</td>,
}

export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={`min-w-0 break-words ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

/** Markdown as plain text, for one-line or clamped previews (cards, lists). */
export function plainText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .split('\n')
    .filter((line) => !/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line)) // table rule lines
    .map((line) =>
      /^\s*\|.*\|\s*$/.test(line)
        ? line.trim().slice(1, -1).split('|').map((c) => c.trim()).join(' · ') // a table row
        : line.replace(/^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+\.\s+)/, ''),
    )
    .join('\n')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/(\*\*|__|\*|_|`)(.+?)\1/g, '$2')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
