/**
 * A Markdown field you edit as rendered text (WYSIWYG), with a switch to the Markdown source.
 * The value is always Markdown: what agents read (instructions, skills, knowledge) stays plain
 * text. Tiptap does the editing; tiptap-markdown reads and writes the Markdown. No raw HTML.
 */
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import Table from '@tiptap/extension-table'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import TableRow from '@tiptap/extension-table-row'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useState } from 'react'
import { Markdown as MarkdownExtension } from 'tiptap-markdown'

import { fieldClass } from './Dialog'
import { Icon } from './ui'

const markdownOf = (editor: Editor): string => (editor.storage as { markdown: { getMarkdown: () => string } }).markdown.getMarkdown()

function Tool({ icon, label, active, onClick }: { icon: string; label: string; active?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onMouseDown={(e) => e.preventDefault()} // keep the selection in the editor
      onClick={onClick}
      className={`flex h-7 w-7 items-center justify-center rounded-lg ${active ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant hover:bg-on-surface/5'}`}
    >
      <Icon name={icon} className="!text-[18px]" />
    </button>
  )
}

function Toolbar({ editor }: { editor: Editor }) {
  const link = () => {
    const was = editor.getAttributes('link').href as string | undefined
    const href = window.prompt('Link address', was ?? 'https://')
    if (href === null) return
    const chain = editor.chain().focus().extendMarkRange('link')
    if (href.trim()) chain.setLink({ href: href.trim() }).run()
    else chain.unsetLink().run()
  }
  return (
    <>
      <Tool icon="format_h1" label="Heading" active={editor.isActive('heading', { level: 2 })} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} />
      <Tool icon="format_bold" label="Bold" active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()} />
      <Tool icon="format_italic" label="Italic" active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()} />
      <Tool icon="code" label="Code" active={editor.isActive('code')} onClick={() => editor.chain().focus().toggleCode().run()} />
      <Tool icon="format_list_bulleted" label="Bulleted list" active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()} />
      <Tool icon="format_list_numbered" label="Numbered list" active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()} />
      <Tool icon="link" label="Link" active={editor.isActive('link')} onClick={link} />
    </>
  )
}

export function MarkdownEditor({
  value,
  onChange,
  label,
  placeholder = '',
  minHeight = 'min-h-48',
}: {
  value: string
  onChange: (markdown: string) => void
  label: string
  placeholder?: string
  minHeight?: string
}) {
  const [source, setSource] = useState(false)
  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false, autolink: true, HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' } }),
      Table,
      TableRow,
      TableHeader,
      TableCell,
      Placeholder.configure({ placeholder }),
      MarkdownExtension.configure({ html: false, linkify: true, transformPastedText: true, transformCopiedText: true }),
    ],
    content: value,
    onUpdate: ({ editor: e }) => onChange(markdownOf(e)),
    editorProps: { attributes: { class: `md-editor max-h-[32rem] overflow-y-auto px-3 py-2 text-sm outline-none ${minHeight}`, 'aria-label': label, role: 'textbox', 'aria-multiline': 'true' } },
  })

  // new text from outside (another agent opened, or edited as source): show it
  useEffect(() => {
    if (editor && !source && markdownOf(editor) !== value) editor.commands.setContent(value, false)
  }, [editor, value, source])

  return (
    <div className="rounded-xl border border-outline-variant bg-surface focus-within:border-primary">
      <div className="flex items-center gap-0.5 border-b border-outline-variant px-1.5 py-1">
        {editor && !source && <Toolbar editor={editor} />}
        <span className="flex-1" />
        <div className="flex rounded-full border border-outline-variant p-0.5" role="group" aria-label="View">
          {(
            [
              [false, 'Rendered'],
              [true, 'Markdown'],
            ] as const
          ).map(([s, name]) => (
            <button
              key={name}
              type="button"
              aria-pressed={source === s}
              onClick={() => setSource(s)}
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${source === s ? 'bg-secondary-container text-on-secondary-container' : 'text-on-surface-variant'}`}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      {source ? (
        <textarea
          aria-label={`${label} (Markdown)`}
          spellCheck={false}
          className={`${fieldClass} !rounded-none !border-0 font-mono text-[13px] leading-relaxed ${minHeight}`}
          rows={16}
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <EditorContent editor={editor} />
      )}
    </div>
  )
}
