import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  FolderOpen,
  LayoutGrid,
  List,
  MessageSquareText,
  PanelRight,
  RefreshCw,
  RotateCcw,
  Search,
  SearchX,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { Button } from '@/components/ui/Button'
import { Input, Select } from '@/components/ui/Field'
import { EmptyState, ErrorState } from '@/components/ui/States'
import { ContextMenu, useContextMenu } from '@/components/ui/ContextMenu'
import { DetailsView, IconsView } from '@/components/files/FileViews'
import { PreviewPane } from '@/components/files/PreviewPane'
import { UploadDialog } from '@/components/files/UploadDialog'
import { useDocuments } from '@/state/DocumentsContext'
import * as api from '@/lib/api'
import { cn, fileKindLabel, formatBytes, formatCount } from '@/lib/format'

const VIEW_STORAGE_KEY = 'port6.files.view'
const PREVIEW_STORAGE_KEY = 'port6.files.preview'

const STATUS_FILTERS = [
  { value: 'all', label: 'All statuses' },
  { value: 'READY', label: 'Ready' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'UPLOADED', label: 'Queued' },
  { value: 'FAILED', label: 'Failed' },
]

function readSetting(key, fallback) {
  try {
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    // Private browsing and locked-down profiles can throw on access.
    return fallback
  }
}

function writeSetting(key, value) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* not worth surfacing; the view still works for this session */
  }
}

/**
 * The document library, as one flat list.
 *
 * There are no folders. PORT-6 stores documents flat and classifies them no
 * further, so any folder shown here would have been invented — every file
 * sits at the top level, the way a single open directory looks.
 */
export function FilesPage() {
  const navigate = useNavigate()
  const { documents, loading, error, ingesting, refresh, removeDocuments } =
    useDocuments()

  const [view, setView] = useState(() => readSetting(VIEW_STORAGE_KEY, 'details'))
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [sortKey, setSortKey] = useState('name')
  const [sortDirection, setSortDirection] = useState('asc')
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [uploadOpen, setUploadOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [reprocessing, setReprocessing] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(
    () => readSetting(PREVIEW_STORAGE_KEY, 'true') === 'true',
  )

  const { menu, openAt, close: closeMenu } = useContextMenu()
  // Anchor for shift-click range selection.
  const anchorRef = useRef(null)

  const availableTypes = useMemo(
    () => [...new Set(documents.map(fileKindLabel))].sort(),
    [documents],
  )

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()

    const filtered = documents.filter((document) => {
      if (statusFilter !== 'all' && document.status !== statusFilter) return false
      if (typeFilter !== 'all' && fileKindLabel(document) !== typeFilter) {
        return false
      }
      if (!needle) return true
      return document.filename.toLowerCase().includes(needle)
    })

    const direction = sortDirection === 'asc' ? 1 : -1

    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case 'size':
          return (a.size_bytes - b.size_bytes) * direction
        case 'modified':
          return (
            (new Date(a.created_at).getTime() -
              new Date(b.created_at).getTime()) *
            direction
          )
        case 'type':
          return fileKindLabel(a).localeCompare(fileKindLabel(b)) * direction
        case 'status':
          return a.status.localeCompare(b.status) * direction
        default:
          return a.filename.localeCompare(b.filename) * direction
      }
    })
  }, [documents, query, statusFilter, typeFilter, sortKey, sortDirection])

  const filtering =
    query.trim() !== '' || statusFilter !== 'all' || typeFilter !== 'all'

  function changeView(next) {
    setView(next)
    writeSetting(VIEW_STORAGE_KEY, next)
  }

  function clearFilters() {
    setQuery('')
    setStatusFilter('all')
    setTypeFilter('all')
  }

  function toggleSort(key) {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortKey(key)
    setSortDirection(key === 'modified' || key === 'size' ? 'desc' : 'asc')
  }

  function selectDocument(document, event) {
    const index = visible.findIndex((item) => item.id === document.id)

    // Shift extends from the anchor; Cmd/Ctrl toggles one; a plain click
    // replaces the selection. Standard everywhere.
    if (event?.shiftKey && anchorRef.current != null) {
      const [from, to] = [anchorRef.current, index].sort((a, b) => a - b)
      setSelectedIds(new Set(visible.slice(from, to + 1).map((item) => item.id)))
      return
    }

    if (event?.metaKey || event?.ctrlKey) {
      setSelectedIds((current) => {
        const next = new Set(current)
        if (next.has(document.id)) next.delete(document.id)
        else next.add(document.id)
        return next
      })
      anchorRef.current = index
      return
    }

    setSelectedIds(new Set([document.id]))
    anchorRef.current = index
  }

  const openDocument = useCallback(
    (document) => navigate(`/files/${document.id}`),
    [navigate],
  )

  // The pane shows a single selection; with several selected there is no
  // one document to describe.
  const previewed =
    selectedIds.size === 1
      ? documents.find((document) => selectedIds.has(document.id)) ?? null
      : null

  const reprocess = useCallback(
    async (document) => {
      setReprocessing(document.id)
      setActionError(null)

      try {
        await api.reprocessDocument(document.id)
        await refresh()
      } catch (caught) {
        setActionError(caught?.message ?? 'Could not reprocess')
      } finally {
        setReprocessing(null)
      }
    },
    [refresh],
  )

  // Documents that failed, or indexed without a summary. Surfaced as a
  // banner because a quiet FAILED row is easy to scroll past.
  const needsAttention = useMemo(
    () =>
      documents.filter(
        (document) =>
          document.status === 'FAILED' ||
          (document.status === 'READY' && !document.summary),
      ),
    [documents],
  )

  const deleteSelected = useCallback(async () => {
    const ids = [...selectedIds]
    if (!ids.length) return

    const confirmed = window.confirm(
      ids.length === 1
        ? 'Delete this document? Its chunks and embeddings are removed too.'
        : `Delete ${ids.length} documents? Their chunks and embeddings are removed too.`,
    )
    if (!confirmed) return

    setDeleting(true)
    setActionError(null)

    try {
      await removeDocuments(ids)
      setSelectedIds(new Set())
    } catch (caught) {
      setActionError(caught?.message ?? 'Could not delete')
    } finally {
      setDeleting(false)
    }
  }, [selectedIds, removeDocuments])

  // Keyboard: the shortcuts a file manager is expected to answer to.
  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if ((event.metaKey || event.ctrlKey) && event.key === 'a') {
        event.preventDefault()
        setSelectedIds(new Set(visible.map((document) => document.id)))
        return
      }

      if (event.key === 'Escape') {
        setSelectedIds(new Set())
        return
      }

      if (event.key === 'Delete' && selectedIds.size > 0) {
        event.preventDefault()
        void deleteSelected()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [visible, selectedIds, deleteSelected])

  const totalBytes = useMemo(
    () => visible.reduce((total, document) => total + (document.size_bytes ?? 0), 0),
    [visible],
  )

  const selectedBytes = useMemo(
    () =>
      documents
        .filter((document) => selectedIds.has(document.id))
        .reduce((total, document) => total + (document.size_bytes ?? 0), 0),
    [documents, selectedIds],
  )

  const menuItems = useMemo(() => {
    const document = menu?.target

    if (!document) {
      return [
        {
          label: 'Upload documents…',
          icon: Upload,
          onSelect: () => setUploadOpen(true),
        },
        { label: 'Refresh', icon: RefreshCw, onSelect: () => void refresh() },
        { separator: true },
        {
          label: 'Select all',
          onSelect: () => setSelectedIds(new Set(visible.map((d) => d.id))),
        },
      ]
    }

    const recoverable =
      document.status === 'FAILED' ||
      (document.status === 'READY' && !document.summary)

    return [
      { label: 'Open', icon: FolderOpen, onSelect: () => openDocument(document) },
      {
        // Scope to the whole selection when there is one, not just the
        // row that was right-clicked.
        label:
          selectedIds.size > 1
            ? `Ask about these ${selectedIds.size} documents`
            : 'Ask about this document',
        icon: MessageSquareText,
        onSelect: () => {
          const scope = selectedIds.has(document.id)
            ? [...selectedIds]
            : [document.id]
          navigate(`/ask?docs=${scope.join(',')}`)
        },
      },
      ...(recoverable
        ? [
            {
              label: 'Reprocess',
              icon: RotateCcw,
              onSelect: () => void reprocess(document),
            },
          ]
        : []),
      { separator: true },
      {
        label:
          selectedIds.size > 1 ? `Delete ${selectedIds.size} documents` : 'Delete',
        icon: Trash2,
        danger: true,
        onSelect: () => void deleteSelected(),
      },
    ]
  }, [
    menu,
    visible,
    openDocument,
    navigate,
    deleteSelected,
    selectedIds,
    refresh,
    reprocess,
  ])

  const emptyLibrary = !loading && documents.length === 0

  return (
    <>
      <Header
        crumbs={[{ label: 'Files' }]}
        actions={
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void refresh()}
              title="Refresh"
              aria-label="Refresh"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', ingesting && 'animate-spin')} />
            </Button>
            <Button size="sm" variant="primary" onClick={() => setUploadOpen(true)}>
              <Upload className="h-3.5 w-3.5" />
              Upload
            </Button>
          </>
        }
      />

      {/* The explorer manages its own scrolling, so it does not use the
          shared PageBody gutter. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-2">
          <h1 className="mr-1 text-sm font-medium">All documents</h1>

          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search files…"
            aria-label="Search files"
            icon={<Search className="h-3.5 w-3.5" />}
            trailing={
              query ? (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="Clear search"
                  className="rounded hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : undefined
            }
            className="w-56"
          />

          <Select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            options={STATUS_FILTERS}
            className="w-36"
          />

          <Select
            aria-label="Filter by type"
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className="w-32"
            options={[
              { value: 'all', label: 'All types' },
              ...availableTypes.map((kind) => ({ value: kind, label: kind })),
            ]}
          />

          {filtering && (
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              Clear
            </Button>
          )}

          <button
            type="button"
            title="Toggle preview pane"
            aria-label="Toggle preview pane"
            aria-pressed={previewOpen}
            onClick={() => {
              const next = !previewOpen
              setPreviewOpen(next)
              writeSetting(PREVIEW_STORAGE_KEY, String(next))
            }}
            className={cn(
              'ml-auto hidden rounded border p-1.5 transition-colors lg:block',
              previewOpen
                ? 'border-line-strong bg-raised text-ink'
                : 'border-line text-ink-subtle hover:text-ink',
            )}
          >
            <PanelRight className="h-3.5 w-3.5" />
          </button>

          <div className="flex rounded border border-line bg-raised p-0.5">
            {[
              { value: 'details', icon: List, label: 'Details view' },
              { value: 'icons', icon: LayoutGrid, label: 'Icon view' },
            ].map((option) => (
              <button
                key={option.value}
                type="button"
                title={option.label}
                aria-label={option.label}
                aria-pressed={view === option.value}
                onClick={() => changeView(option.value)}
                className={cn(
                  'rounded p-1 transition-colors',
                  view === option.value
                    ? 'bg-surface text-ink shadow-panel'
                    : 'text-ink-subtle hover:text-ink',
                )}
              >
                <option.icon className="h-3.5 w-3.5" />
              </button>
            ))}
          </div>
        </div>

        {(error || actionError) && (
          <div className="shrink-0 px-3 pt-3">
            <ErrorState
              title={error ? 'Could not load the library' : 'Action failed'}
              message={error ?? actionError}
              onRetry={error ? () => void refresh() : undefined}
            />
          </div>
        )}

        {needsAttention.length > 0 && (
          <div className="flex shrink-0 items-center gap-2.5 border-b border-warn/25 bg-warn-soft px-3 py-2">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warn" />
            <p className="min-w-0 flex-1 text-xs text-ink-muted">
              <span className="font-medium text-ink">
                {formatCount(needsAttention.length, 'document')}
              </span>{' '}
              did not fully ingest. The uploaded files were kept, so they can
              be reprocessed once the cause is fixed.
            </p>
            <Button
              size="sm"
              loading={reprocessing === 'all'}
              onClick={async () => {
                setReprocessing('all')
                setActionError(null)
                try {
                  for (const document of needsAttention) {
                    await api.reprocessDocument(document.id)
                  }
                  await refresh()
                } catch (caught) {
                  setActionError(caught?.message ?? 'Could not reprocess')
                } finally {
                  setReprocessing(null)
                }
              }}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reprocess all
            </Button>
          </div>
        )}

        {/* File list + preview */}
        <div className="flex min-h-0 flex-1">
        <div
          onContextMenu={(event) => openAt(event, null)}
          onClick={(event) => {
            // Clicking empty space clears the selection, as it should.
            if (event.target === event.currentTarget) setSelectedIds(new Set())
          }}
          className="min-h-0 min-w-0 flex-1 overflow-auto"
        >
          {emptyLibrary ? (
            <EmptyState
              icon={FolderOpen}
              title="No documents yet"
              description="Upload your first document to build your knowledge base."
              action={
                <Button variant="primary" onClick={() => setUploadOpen(true)}>
                  <Upload className="h-3.5 w-3.5" />
                  Upload documents
                </Button>
              }
            />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No files match these filters"
              description="Try a different search term, or clear the filters."
              action={<Button onClick={clearFilters}>Clear filters</Button>}
            />
          ) : view === 'details' ? (
            <DetailsView
              documents={visible}
              selectedIds={selectedIds}
              sortKey={sortKey}
              sortDirection={sortDirection}
              onSort={toggleSort}
              onSelect={selectDocument}
              onOpen={openDocument}
              onContextMenu={(event, document) => {
                if (!selectedIds.has(document.id)) selectDocument(document)
                openAt(event, document)
              }}
            />
          ) : (
            <IconsView
              documents={visible}
              selectedIds={selectedIds}
              onSelect={selectDocument}
              onOpen={openDocument}
              onContextMenu={(event, document) => {
                if (!selectedIds.has(document.id)) selectDocument(document)
                openAt(event, document)
              }}
            />
          )}
        </div>

        {previewOpen && (
          <PreviewPane
            document={previewed}
            onClose={() => setPreviewOpen(false)}
            onReprocess={reprocess}
            reprocessing={reprocessing === previewed?.id}
          />
        )}
        </div>

        {/* Status bar */}
        <div className="flex shrink-0 items-center gap-3 border-t border-line bg-surface px-3 py-1.5 text-2xs text-ink-muted">
          <span className="tnum">
            {formatCount(visible.length, 'item')}
            {filtering && ` of ${documents.length}`}
          </span>

          {selectedIds.size > 0 && (
            <>
              <span className="text-ink-subtle">·</span>
              <span className="tnum">{selectedIds.size} selected</span>
              <Button
                size="sm"
                variant="danger"
                loading={deleting}
                onClick={() => void deleteSelected()}
                className="h-5 px-1.5 text-2xs"
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </Button>
            </>
          )}

          <span className="ml-auto flex items-center gap-3">
            {ingesting && (
              <span className="flex items-center gap-1.5 text-accent">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                Ingesting
              </span>
            )}
            {/* Labelled, and it follows the selection — an unlabelled
                figure here reads as a control that does nothing. */}
            <span className="tnum">
              {selectedIds.size > 0
                ? `${formatBytes(selectedBytes)} selected of ${formatBytes(totalBytes)}`
                : `${formatBytes(totalBytes)} total`}
            </span>
          </span>
        </div>
      </div>

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={closeMenu} />
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        documents={documents}
        onUploaded={() => void refresh()}
      />
    </>
  )
}
