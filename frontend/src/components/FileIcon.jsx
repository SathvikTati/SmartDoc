import { File, FileCode, FileText, FileType2, Folder, FolderOpen } from 'lucide-react'

import { cn, extensionOf } from '@/lib/format'

/**
 * Colour carries the file type here, so the icon shape can stay familiar.
 * Muted tones only — this appears on every row of a long list.
 */
const BY_EXTENSION = {
  pdf: { icon: FileType2, className: 'text-danger/75' },
  docx: { icon: FileText, className: 'text-accent/75' },
  doc: { icon: FileText, className: 'text-accent/75' },
  md: { icon: FileCode, className: 'text-ok/75' },
  markdown: { icon: FileCode, className: 'text-ok/75' },
  txt: { icon: FileText, className: 'text-ink-subtle' },
}

export function FileIcon({ filename, className }) {
  const config = BY_EXTENSION[extensionOf(filename)] ?? {
    icon: File,
    className: 'text-ink-subtle',
  }

  const Icon = config.icon

  return (
    <Icon
      aria-hidden="true"
      className={cn('h-4 w-4 shrink-0', config.className, className)}
    />
  )
}

export function FolderIcon({ open = false, className }) {
  const Icon = open ? FolderOpen : Folder

  return (
    <Icon
      aria-hidden="true"
      className={cn('h-4 w-4 shrink-0 text-warn/80', className)}
    />
  )
}
