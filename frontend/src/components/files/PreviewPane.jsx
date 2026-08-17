import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  ListTree,
  MessageSquareText,
  RotateCcw,
  X,
} from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { StatusBadge } from '@/components/ui/Badge'
import { SkeletonBlock } from '@/components/ui/States'
import { FileIcon } from '@/components/FileIcon'
import * as api from '@/lib/api'
import {
  cn,
  fileKindLabel,
  formatBytes,
  formatDateTime,
  formatRelative,
} from '@/lib/format'

function Fact({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-ink-subtle">{label}</span>
      <span className="tnum truncate text-ink">{value}</span>
    </div>
  )
}

/**
 * The right-hand pane of the file manager: what a document is, without
 * leaving the list.
 *
 * Structure is fetched per selection and cached for the session — it
 * re-parses the file on the server, so it is worth not asking twice.
 */
export function PreviewPane({ document, onClose, onReprocess, reprocessing }) {
  const [structure, setStructure] = useState(null)
  const [loading, setLoading] = useState(false)
  const [cache] = useState(() => new Map())

  const load = useCallback(
    async (id, status) => {
      if (cache.has(id)) {
        setStructure(cache.get(id))
        return
      }

      setLoading(true)
      setStructure(null)

      try {
        const tree = await api.getDocumentStructure(id)

        // Only cache a settled document; one mid-ingestion will change.
        if (status === 'READY' || status === 'FAILED') cache.set(id, tree)

        setStructure(tree)
      } catch {
        setStructure(null)
      } finally {
        setLoading(false)
      }
    },
    [cache],
  )

  useEffect(() => {
    if (!document) return
    void load(document.id, document.status)
  }, [document, load])

  if (!document) {
    return (
      <aside className="hidden w-72 shrink-0 flex-col border-l border-line bg-surface lg:flex">
        <div className="flex flex-1 items-center justify-center px-6 text-center">
          <p className="text-xs leading-5 text-ink-subtle">
            Select a file to see its summary and structure.
          </p>
        </div>
      </aside>
    )
  }

  const failed = document.status === 'FAILED'
  const missingSummary = document.status === 'READY' && !document.summary

  return (
    <aside className="hidden w-72 shrink-0 flex-col border-l border-line bg-surface lg:flex">
      <div className="flex items-start gap-2 border-b border-line px-3 py-2.5">
        <FileIcon filename={document.filename} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p
            className="break-all text-sm font-medium leading-5"
            title={document.filename}
          >
            {document.filename}
          </p>
          <div className="mt-1">
            <StatusBadge status={document.status} />
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close preview"
          className="rounded p-0.5 text-ink-subtle transition-colors hover:bg-raised hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {(failed || missingSummary) && (
          <div
            className={cn(
              'rounded border px-2.5 py-2',
              failed
                ? 'border-danger/25 bg-danger-soft'
                : 'border-warn/25 bg-warn-soft',
            )}
          >
            <div className="flex items-start gap-2">
              <AlertTriangle
                className={cn(
                  'mt-0.5 h-3.5 w-3.5 shrink-0',
                  failed ? 'text-danger' : 'text-warn',
                )}
              />
              <div className="min-w-0">
                <p className="text-xs font-medium text-ink">
                  {failed ? 'Ingestion failed' : 'Indexed without a summary'}
                </p>
                <p className="mt-0.5 break-words text-xs leading-4 text-ink-muted">
                  {document.error_message ??
                    'This document cannot be ranked at the document level.'}
                </p>
              </div>
            </div>

            <Button
              size="sm"
              className="mt-2 w-full"
              loading={reprocessing}
              onClick={() => onReprocess(document)}
            >
              {!reprocessing && <RotateCcw className="h-3.5 w-3.5" />}
              Reprocess
            </Button>
          </div>
        )}

        <div className="space-y-1">
          <Fact label="Type" value={fileKindLabel(document)} />
          <Fact label="Size" value={formatBytes(document.size_bytes)} />
          <Fact label="Chunks" value={structure?.chunk_count ?? '—'} />
          <Fact label="Pages" value={structure?.page_count ?? '—'} />
          <Fact label="Sections" value={structure?.sections.length ?? '—'} />
          <Fact
            label="Attempts"
            value={document.attempts ?? 0}
          />
          <Fact
            label="Added"
            value={
              <span title={formatDateTime(document.created_at)}>
                {formatRelative(document.created_at)}
              </span>
            }
          />
        </div>

        <div>
          <h3 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
            Summary
          </h3>
          {document.summary ? (
            <p className="text-xs leading-5 text-ink-muted">
              {document.summary}
            </p>
          ) : document.status === 'PROCESSING' ||
            document.status === 'UPLOADED' ? (
            <SkeletonBlock lines={3} />
          ) : (
            <p className="text-xs text-ink-subtle">None generated.</p>
          )}
        </div>

        <div>
          <h3 className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
            <ListTree className="h-3 w-3" />
            Structure
          </h3>

          {loading ? (
            <SkeletonBlock lines={4} />
          ) : structure?.sections?.length ? (
            <ol className="space-y-0.5">
              {structure.sections.slice(0, 40).map((section) => (
                <li
                  key={section.section_id}
                  style={{ paddingLeft: `${(section.level - 1) * 10}px` }}
                  className={cn(
                    'truncate text-xs',
                    section.level === 1
                      ? 'font-medium text-ink'
                      : 'text-ink-muted',
                  )}
                  title={section.path.join(' > ')}
                >
                  {section.title}
                </li>
              ))}
              {structure.sections.length > 40 && (
                <li className="pt-1 text-2xs text-ink-subtle">
                  +{structure.sections.length - 40} more
                </li>
              )}
            </ol>
          ) : (
            <p className="text-xs text-ink-subtle">
              {structure && !structure.structure_available
                ? 'The stored file is gone, so headings could not be read.'
                : 'No headings detected.'}
            </p>
          )}
        </div>
      </div>

      <div className="space-y-1.5 border-t border-line p-2.5">
        <Link to={`/files/${document.id}`} className="block">
          <Button size="sm" className="w-full">
            <FileText className="h-3.5 w-3.5" />
            Open document
            <ExternalLink className="h-2.5 w-2.5" />
          </Button>
        </Link>
        <Link
          to={`/ask?docs=${document.id}`}
          className="block"
        >
          <Button size="sm" variant="primary" className="w-full">
            <MessageSquareText className="h-3.5 w-3.5" />
            Ask about this
          </Button>
        </Link>
      </div>
    </aside>
  )
}
