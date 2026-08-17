import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  FileText,
  ListTree,
  MessageSquareText,
  Trash2,
} from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Disclosure } from '@/components/ui/Disclosure'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import { FileIcon } from '@/components/FileIcon'
import * as api from '@/lib/api'
import { useDocuments } from '@/state/DocumentsContext'
import {
  cn,
  fileKindLabel,
  formatBytes,
  formatDateTime,
  formatRelative,
} from '@/lib/format'

/** `items` are `{ label, value }`. */
function Facts({ items }) {
  return (
    <dl className="tnum flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <dt className="text-ink-subtle">{item.label}</dt>
          <dd className="text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function StructureTree({ structure }) {
  if (!structure.structure_available) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Structure unavailable"
        description="The stored file is no longer on disk, so its headings could not be re-read. The document is still fully searchable by chunk."
      />
    )
  }

  if (!structure.sections.length) {
    return (
      <EmptyState
        icon={ListTree}
        title="No headings detected"
        description="This document was indexed as a single unstructured section."
      />
    )
  }

  return (
    <ol className="py-1">
      {structure.sections.map((section) => (
        <li
          key={section.section_id}
          // Indent by heading depth so the outline reads as an outline.
          style={{ paddingLeft: `${(section.level - 1) * 18 + 12}px` }}
          className="flex items-baseline gap-2 py-1 pr-3 hover:bg-raised/60"
        >
          <span
            className={cn(
              'min-w-0 flex-1 truncate',
              section.level === 1
                ? 'text-sm font-medium text-ink'
                : 'text-sm text-ink-muted',
            )}
            title={section.path.join(' > ')}
          >
            {section.title}
          </span>

          <span className="tnum shrink-0 text-2xs text-ink-subtle">
            {section.page_start != null &&
              `p. ${section.page_start}${
                section.page_end && section.page_end !== section.page_start
                  ? `–${section.page_end}`
                  : ''
              } · `}
            {section.has_content
              ? `${section.character_count} chars`
              : 'heading only'}
          </span>
        </li>
      ))}
    </ol>
  )
}

export function DocumentDetailPage() {
  const { documentId } = useParams()
  const navigate = useNavigate()
  const { removeDocuments } = useDocuments()

  const [document, setDocument] = useState(null)
  const [structure, setStructure] = useState(null)
  const [content, setContent] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    if (!documentId) return

    setError(null)

    try {
      // Structure re-parses the file, so it is fetched alongside rather
      // than blocking the metadata that is already in Postgres.
      const [summary, tree] = await Promise.all([
        api.getDocument(documentId),
        api.getDocumentStructure(documentId).catch(() => null),
      ])

      setDocument(summary)
      setStructure(tree)
    } catch (caught) {
      setError(caught?.message ?? 'Could not load this document')
    } finally {
      setLoading(false)
    }
  }, [documentId])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load])

  // While ingestion is running the counts and structure are still changing.
  useEffect(() => {
    if (!document) return
    if (document.status !== 'PROCESSING' && document.status !== 'UPLOADED') return

    const timer = window.setInterval(() => void load(), 2_000)
    return () => window.clearInterval(timer)
  }, [document, load])

  async function loadContent() {
    if (content || !documentId) return
    try {
      setContent(await api.getDocumentContent(documentId))
    } catch {
      // The disclosure simply stays empty; the page is still usable.
    }
  }

  async function remove() {
    if (!document) return

    const confirmed = window.confirm(
      `Delete ${document.filename}? Its chunks and embeddings are removed too.`,
    )
    if (!confirmed) return

    setDeleting(true)
    try {
      await removeDocuments([document.id])
      navigate('/files')
    } catch (caught) {
      setError(caught?.message ?? 'Could not delete')
      setDeleting(false)
    }
  }

  const crumbs = [
    { label: 'Files', to: '/files' },
    { label: document?.filename ?? 'Document' },
  ]

  if (error && !document) {
    return (
      <>
        <Header crumbs={crumbs} />
        <PageBody>
          <ErrorState
            title="Could not load this document"
            message={error}
            onRetry={() => void load()}
          />
          <div className="mt-4">
            <Link to="/files">
              <Button>
                <ArrowLeft className="h-3.5 w-3.5" />
                Back to files
              </Button>
            </Link>
          </div>
        </PageBody>
      </>
    )
  }

  return (
    <>
      <Header
        crumbs={crumbs}
        actions={
          document && (
            <>
              <Link to={`/ask?document=${encodeURIComponent(document.filename)}`}>
                <Button size="sm" variant="primary">
                  <MessageSquareText className="h-3.5 w-3.5" />
                  Ask about this document
                </Button>
              </Link>
              <Button
                size="sm"
                variant="danger"
                loading={deleting}
                onClick={() => void remove()}
                aria-label="Delete document"
                title="Delete document"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          )
        }
      />

      <PageBody>
        {loading && !document ? (
          <div className="space-y-6">
            <SkeletonBlock lines={2} />
            <SkeletonBlock lines={4} />
          </div>
        ) : (
          document && (
            <div className="space-y-7">
              {error && <ErrorState message={error} />}

              {/* Identity */}
              <div>
                <div className="flex items-start gap-2.5">
                  <FileIcon filename={document.filename} className="mt-1 h-5 w-5" />
                  <div className="min-w-0 flex-1">
                    <h1 className="text-xl font-semibold tracking-tight">
                      {document.filename}
                    </h1>
                  </div>
                  <StatusBadge status={document.status} />
                </div>

                <div className="mt-3">
                  <Facts
                    items={[
                      { label: 'Type', value: fileKindLabel(document) },
                      { label: 'Size', value: formatBytes(document.size_bytes) },
                      { label: 'Pages', value: structure?.page_count ?? '—' },
                      {
                        label: 'Chunks',
                        // Counted in the vector store, so it reflects what
                        // is actually retrievable rather than what parsing
                        // produced.
                        value: structure?.chunk_count ?? '—',
                      },
                      {
                        label: 'Sections',
                        value: structure?.sections.length ?? '—',
                      },
                      {
                        label: 'Uploaded',
                        value: (
                          <span title={formatDateTime(document.created_at)}>
                            {formatRelative(document.created_at)}
                          </span>
                        ),
                      },
                    ]}
                  />
                </div>
              </div>

              {document.status === 'FAILED' && document.error_message && (
                <ErrorState
                  title="Ingestion failed"
                  message={document.error_message}
                />
              )}

              {/* Summary */}
              <section>
                <SectionHeading title="Summary" meta="generated at ingestion" />
                {document.summary ? (
                  <p className="max-w-3xl text-sm leading-6 text-ink-muted">
                    {document.summary}
                  </p>
                ) : document.status === 'PROCESSING' ||
                  document.status === 'UPLOADED' ? (
                  <SkeletonBlock lines={3} />
                ) : (
                  <p className="text-sm text-ink-subtle">
                    No summary was produced. Summarisation is best-effort — the
                    document is still fully indexed and queryable.
                  </p>
                )}
              </section>

              {/* Structure */}
              <section>
                <SectionHeading
                  title="Document structure"
                  meta={
                    structure
                      ? `${structure.sections.length} sections · ${structure.chunk_count} chunks indexed`
                      : undefined
                  }
                />
                <Panel className="overflow-hidden">
                  {structure ? (
                    <StructureTree structure={structure} />
                  ) : (
                    <div className="p-3">
                      <SkeletonBlock lines={5} />
                    </div>
                  )}
                </Panel>
              </section>

              {/* Extracted text, on demand: it can be long and is rarely
                  the reason someone opens this page. */}
              <section>
                <Disclosure
                  title="Extracted text"
                  meta={
                    structure
                      ? `${structure.character_count.toLocaleString()} characters`
                      : undefined
                  }
                >
                  <div className="p-3">
                    {content ? (
                      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-raised p-3 font-mono text-xs leading-5 text-ink-muted">
                        {content.content}
                      </pre>
                    ) : (
                      <Button size="sm" onClick={() => void loadContent()}>
                        <FileText className="h-3.5 w-3.5" />
                        Load extracted text
                      </Button>
                    )}
                  </div>
                </Disclosure>
              </section>
            </div>
          )
        )}
      </PageBody>
    </>
  )
}
