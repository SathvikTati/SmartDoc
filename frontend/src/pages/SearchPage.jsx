import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, Search, SearchX } from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Input, Label, SegmentedControl, Select } from '@/components/ui/Field'
import { Panel } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import { FileIcon } from '@/components/FileIcon'
import * as api from '@/lib/api'
import { cn } from '@/lib/format'
import { useDocuments } from '@/state/DocumentsContext'

const MODES = [
  {
    value: 'semantic',
    label: 'Semantic',
    hint: 'Dense vectors only. Scores are Chroma distances — lower is closer.',
  },
  {
    value: 'keyword',
    label: 'Keyword',
    hint: 'BM25 only. Scores are relevance — higher is better.',
  },
  {
    value: 'hybrid',
    label: 'Hybrid',
    hint: 'Both, fused with Reciprocal Rank Fusion.',
  },
]

function MatchTag({ label, hit, rank }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs',
        hit
          ? 'border-ok/20 bg-ok-soft text-ok'
          : 'border-line bg-raised text-ink-subtle/70',
      )}
    >
      {hit ? '✓' : '—'} {label}
      {hit && rank != null && <span className="tnum opacity-70">#{rank}</span>}
    </span>
  )
}

export function SearchPage() {
  const { documents } = useDocuments()

  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [topK, setTopK] = useState(8)
  const [response, setResponse] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const abortRef = useRef(null)

  async function run() {
    const trimmed = query.trim()
    if (!trimmed) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setError(null)

    try {
      setResponse(await api.search(trimmed, mode, topK, controller.signal))
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught?.message ?? 'Search failed')
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const activeMode = MODES.find((option) => option.value === mode)
  const empty = documents.length === 0

  return (
    <>
      <Header crumbs={[{ label: 'Search' }]} />

      <PageBody>
        <div className="mb-5">
          <h1 className="text-lg font-semibold tracking-tight">
            Search documents
          </h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            Raw chunk retrieval, with no model in the loop. This is what the
            answering pipeline sees before it generates anything.
          </p>
        </div>

        <div className="mb-5 space-y-3">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void run()
            }}
            className="flex gap-2"
          >
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="annual leave eligibility"
              aria-label="Search query"
              icon={<Search className="h-3.5 w-3.5" />}
              className="flex-1"
            />
            <Button
              type="submit"
              variant="primary"
              loading={running}
              disabled={!query.trim() || empty}
            >
              Search
            </Button>
          </form>

          <div className="flex flex-wrap items-end gap-5">
            <div>
              <Label className="mb-1">Mode</Label>
              <SegmentedControl
                name="search-mode"
                value={mode}
                options={MODES}
                onChange={setMode}
              />
            </div>

            <div>
              <Label htmlFor="search-top-k" className="mb-1">
                Results
              </Label>
              <Select
                id="search-top-k"
                value={String(topK)}
                onChange={(event) => setTopK(Number(event.target.value))}
                className="w-20"
                options={[5, 8, 10, 15, 20].map((value) => ({
                  value: String(value),
                  label: String(value),
                }))}
              />
            </div>

            {activeMode && (
              <p className="min-w-0 flex-1 pb-1.5 text-xs text-ink-subtle">
                {activeMode.hint}
              </p>
            )}
          </div>
        </div>

        {error && (
          <ErrorState
            title="Search failed"
            message={error}
            onRetry={() => void run()}
            className="mb-5"
          />
        )}

        {running && (
          <Panel className="p-4">
            <SkeletonBlock lines={5} />
          </Panel>
        )}

        {!running && !response && (
          <Panel>
            {empty ? (
              <EmptyState
                icon={SearchX}
                title="Nothing to search"
                description="The library is empty. Upload documents first."
                action={
                  <Link to="/files">
                    <Button variant="primary">Go to files</Button>
                  </Link>
                }
              />
            ) : (
              <EmptyState
                icon={Search}
                title="Search your document library"
                description="Enter a query to inspect the retrieved chunks, their sections, pages and retriever ranks."
              />
            )}
          </Panel>
        )}

        {!running && response && (
          <>
            <div className="mb-2 flex items-baseline justify-between">
              <p className="text-sm text-ink-muted">
                <span className="tnum font-medium text-ink">
                  {response.results.length}
                </span>{' '}
                {response.results.length === 1 ? 'chunk' : 'chunks'} for{' '}
                <span className="text-ink">“{response.query}”</span>
              </p>
              <Badge tone="neutral" className="capitalize">
                {response.mode}
              </Badge>
            </div>

            <Panel className="divide-y divide-line">
              {response.results.map((result) => (
                <article
                  key={result.chunk_id}
                  className="px-3 py-2.5 transition-colors hover:bg-raised/50"
                >
                  <div className="flex items-start gap-2">
                    <span className="tnum mt-0.5 w-5 shrink-0 text-xs text-ink-subtle">
                      {result.rank}
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <FileIcon
                          filename={result.filename}
                          className="h-3.5 w-3.5"
                        />
                        <span className="truncate text-sm font-medium">
                          {result.filename}
                        </span>
                        {result.section_title && (
                          <span className="truncate text-xs text-ink-muted">
                            Section {result.section_title}
                          </span>
                        )}
                        {result.page_number != null && (
                          <span className="text-xs text-ink-subtle">
                            Page {result.page_number}
                          </span>
                        )}
                      </div>

                      {result.section_path && (
                        <p className="mt-0.5 truncate text-2xs text-ink-subtle">
                          {result.section_path}
                        </p>
                      )}

                      <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-ink-muted">
                        {result.content}
                      </p>

                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <MatchTag
                          label="Semantic"
                          hit={result.sources.includes('semantic')}
                          rank={result.semantic_rank}
                        />
                        <MatchTag
                          label="Keyword"
                          hit={result.sources.includes('keyword')}
                          rank={result.keyword_rank}
                        />

                        {result.score != null && (
                          <span className="tnum text-2xs text-ink-subtle">
                            {result.sources.length === 1 &&
                            result.sources[0] === 'keyword'
                              ? 'BM25'
                              : 'distance'}{' '}
                            {result.score.toFixed(4)}
                          </span>
                        )}
                        {result.fused_score != null && (
                          <span className="tnum text-2xs text-ink-subtle">
                            · RRF {result.fused_score.toFixed(5)}
                          </span>
                        )}
                        <span className="tnum text-2xs text-ink-subtle">
                          · chunk {result.chunk_index}
                        </span>

                        <Link
                          to={`/files/${result.document_id}`}
                          className="ml-auto inline-flex items-center gap-1 rounded text-2xs text-accent hover:underline"
                        >
                          Open document
                          <ExternalLink className="h-2.5 w-2.5" />
                        </Link>
                      </div>
                    </div>
                  </div>
                </article>
              ))}

              {response.results.length === 0 && (
                <EmptyState
                  icon={SearchX}
                  title="No results"
                  description={
                    mode === 'keyword'
                      ? 'No chunk shares a term with this query. BM25 matches words literally — try semantic mode.'
                      : 'Nothing in the index matched. Try different wording.'
                  }
                />
              )}
            </Panel>
          </>
        )}
      </PageBody>
    </>
  )
}
