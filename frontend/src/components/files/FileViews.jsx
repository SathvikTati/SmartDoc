import { ArrowDown, ArrowUp } from 'lucide-react'

import { StatusBadge, StatusDot } from '@/components/ui/Badge'
import { FileIcon } from '@/components/FileIcon'
import {
  cn,
  fileKindLabel,
  formatBytes,
  formatRelative,
} from '@/lib/format'

/** Shared row/tile behaviour: click selects, double-click opens. */
function interactionProps({ document, selected, onSelect, onOpen, onContextMenu }) {
  return {
    onClick: (event) => onSelect(document, event),
    onDoubleClick: () => onOpen(document),
    onContextMenu: (event) => onContextMenu(event, document),
    onKeyDown: (event) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        onOpen(document)
      }
    },
    tabIndex: 0,
    role: 'option',
    'aria-selected': selected,
  }
}

const COLUMNS = [
  { key: 'name', label: 'Name', className: 'min-w-[240px]' },
  { key: 'type', label: 'Type', className: 'w-28' },
  { key: 'size', label: 'Size', className: 'w-24 text-right' },
  { key: 'status', label: 'Status', className: 'w-28' },
  { key: 'modified', label: 'Date added', className: 'w-28' },
]

export function DetailsView({
  documents,
  selectedIds,
  sortKey,
  sortDirection,
  onSort,
  onSelect,
  onOpen,
  onContextMenu,
}) {
  return (
    <table
      className="w-full border-collapse text-sm"
      role="listbox"
      aria-label="Documents"
    >
      <thead className="sticky top-0 z-10 bg-canvas">
        <tr className="border-b border-line text-left">
          {COLUMNS.map((column) => (
            <th
              key={column.key}
              scope="col"
              className={cn('px-3 py-1.5 font-normal', column.className)}
            >
              <button
                type="button"
                onClick={() => onSort(column.key)}
                className={cn(
                  'inline-flex items-center gap-1 rounded text-2xs uppercase tracking-wide',
                  'transition-colors hover:text-ink',
                  sortKey === column.key ? 'text-ink' : 'text-ink-subtle',
                )}
              >
                {column.label}
                {sortKey === column.key &&
                  (sortDirection === 'asc' ? (
                    <ArrowUp className="h-3 w-3" />
                  ) : (
                    <ArrowDown className="h-3 w-3" />
                  ))}
              </button>
            </th>
          ))}
        </tr>
      </thead>

      <tbody>
        {documents.map((document) => {
          const selected = selectedIds.has(document.id)

          return (
            <tr
              key={document.id}
              {...interactionProps({
                document,
                selected,
                onSelect,
                onOpen,
                onContextMenu,
              })}
              className={cn(
                'cursor-default border-b border-line/60 select-none',
                selected ? 'bg-accent-soft' : 'hover:bg-raised/70',
              )}
            >
              <td className="px-3 py-1.5">
                <div className="flex items-center gap-2">
                  <FileIcon filename={document.filename} />
                  <span className="truncate">{document.filename}</span>
                </div>
              </td>

              <td className="px-3 py-1.5 text-ink-muted">
                {fileKindLabel(document)}
              </td>

              <td className="tnum px-3 py-1.5 text-right text-ink-muted">
                {formatBytes(document.size_bytes)}
              </td>

              <td className="px-3 py-1.5">
                <StatusBadge status={document.status} />
              </td>

              <td
                className="px-3 py-1.5 text-ink-muted"
                title={new Date(document.created_at).toLocaleString()}
              >
                {formatRelative(document.created_at)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export function IconsView({
  documents,
  selectedIds,
  onSelect,
  onOpen,
  onContextMenu,
}) {
  return (
    <div
      role="listbox"
      aria-label="Documents"
      className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-1 p-2"
    >
      {documents.map((document) => {
        const selected = selectedIds.has(document.id)

        return (
          <div
            key={document.id}
            {...interactionProps({
              document,
              selected,
              onSelect,
              onOpen,
              onContextMenu,
            })}
            className={cn(
              'flex cursor-default flex-col items-center gap-1.5 rounded p-2.5 select-none',
              selected ? 'bg-accent-soft' : 'hover:bg-raised/70',
            )}
          >
            <div className="relative">
              <FileIcon filename={document.filename} className="h-9 w-9" />

              {document.status !== 'READY' && (
                <StatusDot
                  status={document.status}
                  className="absolute -right-0.5 -top-0.5 h-2 w-2 ring-2 ring-canvas"
                />
              )}
            </div>

            <span
              className="line-clamp-2 break-all text-center text-xs leading-4 text-ink"
              title={document.filename}
            >
              {document.filename}
            </span>

            <span className="tnum text-2xs text-ink-subtle">
              {formatBytes(document.size_bytes)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
