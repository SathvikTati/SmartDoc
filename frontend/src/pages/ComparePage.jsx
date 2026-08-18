import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Columns3, Minus, X } from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { Button } from '@/components/ui/Button'
import { Disclosure } from '@/components/ui/Disclosure'
import { Label, Select, Textarea } from '@/components/ui/Field'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import { RetrievalTrace } from '@/components/rag/RetrievalTrace'
import { ChunkCard } from '@/components/rag/ChunkCard'
import * as api from '@/lib/api'
import { RAG_MODES } from '@/lib/constants'
import { cn, formatLatency } from '@/lib/format'
import { useDocuments } from '@/state/DocumentsContext'

/** One metric row of the comparison table. */
// This page compares the three families. Picking specific pipelines
// within a family is what /pipelines is for.
const MODE_LABELS = {
  naive: 'Naive',
  hybrid: 'Hybrid',
  agentic: 'Agentic',
}

const METRICS = [
  {
    label: 'Answered',
    render: (result) =>
      result.answered ? (
        <Check className="mx-auto h-4 w-4 text-ok" />
      ) : (
        <X className="mx-auto h-4 w-4 text-warn" />
      ),
  },
  {
    label: 'Citations',
    render: (result) => result.citations.length,
  },
  {
    label: 'Chunks in context',
    render: (result) => result.retrieved_chunks.length,
  },
  {
    label: 'Documents drawn on',
    render: (result) =>
      new Set(result.retrieved_chunks.map((chunk) => chunk.document_id)).size,
  },
  {
    label: 'Latency',
    render: (result) => formatLatency(result.latency_ms),
    // Fastest wins — the only row where a lower number is unambiguously
    // better, so it is the only one marked.
    best: (results) => {
      let bestIndex = null
      let bestValue = Infinity

      results.forEach((result, index) => {
        if (result?.latency_ms != null && result.latency_ms < bestValue) {
          bestValue = result.latency_ms
          bestIndex = index
        }
      })

      return bestIndex
    },
  },
  {
    label: 'Retrieval method',
    render: (result) => (
      <span className="text-xs text-ink-muted">{result.retrieval_method}</span>
    ),
  },
]

/** One mode's retrieved chunks, each independently expandable. */
function ModeEvidence({ result }) {
  const [expanded, setExpanded] = useState(new Set())

  const cited = new Set(result.citations.map((citation) => citation.chunk_id))

  return (
    <Disclosure
      bordered={false}
      title="Evidence"
      meta={`${result.retrieved_chunks.length} chunks`}
    >
      <div className="divide-y divide-line border-t border-line">
        {result.retrieved_chunks.map((chunk) => (
          <ChunkCard
            key={chunk.chunk_id}
            chunk={chunk}
            cited={cited.has(chunk.chunk_id)}
            expanded={expanded.has(chunk.chunk_id)}
            onToggle={() =>
              setExpanded((current) => {
                const next = new Set(current)
                if (next.has(chunk.chunk_id)) next.delete(chunk.chunk_id)
                else next.add(chunk.chunk_id)
                return next
              })
            }
          />
        ))}
      </div>
    </Disclosure>
  )
}

export function ComparePage() {
  const { documents } = useDocuments()

  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(5)
  const [response, setResponse] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const abortRef = useRef(null)

  const readyCount = documents.filter(
    (document) => document.status === 'READY',
  ).length

  async function run() {
    const trimmed = question.trim()
    if (!trimmed) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setError(null)

    try {
      setResponse(
        await api.compare(trimmed, {
          modes: RAG_MODES,
          topK,
          signal: controller.signal,
        }),
      )
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught?.message ?? 'Comparison failed')
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const results = response
    ? RAG_MODES.map((mode) => response.results[mode]).filter(Boolean)
    : []

  return (
    <>
      <Header crumbs={[{ label: 'Compare' }]} />

      <PageBody>
        <div className="mb-5">
          <h1 className="text-lg font-semibold tracking-tight">
            Compare retrieval strategies
          </h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            One question, run through all three modes, so the cost of the more
            advanced strategies can be weighed against what they buy.
          </p>
        </div>

        <div className="mb-5 space-y-3">
          <div className="relative">
            <Textarea
              rows={2}
              value={question}
              disabled={running}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void run()
                }
              }}
              placeholder="Ask one question to run through every mode…"
              aria-label="Question"
              className="pr-36"
            />
            <div className="absolute bottom-2 right-2">
              <Button
                variant="primary"
                loading={running}
                disabled={!question.trim() || !readyCount}
                onClick={() => void run()}
              >
                {running ? 'Running 3 modes…' : 'Run comparison'}
              </Button>
            </div>
          </div>

          <div className="flex items-end gap-5">
            <div>
              <Label htmlFor="compare-top-k" className="mb-1">
                Top K
              </Label>
              <Select
                id="compare-top-k"
                value={String(topK)}
                disabled={running}
                onChange={(event) => setTopK(Number(event.target.value))}
                className="w-20"
                options={[3, 5, 8, 10].map((value) => ({
                  value: String(value),
                  label: String(value),
                }))}
              />
            </div>
            <p className="pb-1.5 text-xs text-ink-subtle">
              Three pipelines run back to back against the same model, so this
              takes roughly the sum of the three latencies.
            </p>
          </div>
        </div>

        {error && (
          <ErrorState
            title="Comparison failed"
            message={error}
            onRetry={() => void run()}
            className="mb-5"
          />
        )}

        {running && (
          <Panel className="p-4">
            <div className="mb-3 flex items-center gap-2 text-sm text-ink-muted">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              Running naive, hybrid and agentic in sequence…
            </div>
            <SkeletonBlock lines={5} />
          </Panel>
        )}

        {!running && !response && (
          <Panel>
            {readyCount === 0 ? (
              <EmptyState
                icon={Columns3}
                title="Nothing to compare"
                description="No documents are ready. Upload some first."
                action={
                  <Link to="/files">
                    <Button variant="primary">Go to files</Button>
                  </Link>
                }
              />
            ) : (
              <EmptyState
                icon={Columns3}
                title="Compare all three modes"
                description="Ask one question to see how naive, hybrid and agentic retrieval differ on the same input."
              />
            )}
          </Panel>
        )}

        {!running && response && (
          <div className="space-y-8">
            {/* Metric table */}
            <div>
              <SectionHeading title="At a glance" meta={response.question} />
              <Panel className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="bg-raised/60">
                        <th
                          scope="col"
                          className="w-48 px-3 py-2 text-left text-2xs font-medium uppercase tracking-wide text-ink-muted"
                        >
                          Metric
                        </th>
                        {RAG_MODES.map((mode) => (
                          <th
                            key={mode}
                            scope="col"
                            className="px-3 py-2 text-center text-2xs font-medium uppercase tracking-wide text-ink"
                          >
                            {MODE_LABELS[mode] ?? mode}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {METRICS.map((metric) => {
                        const winner = metric.best?.(results) ?? null

                        return (
                          <tr key={metric.label} className="border-t border-line">
                            <th
                              scope="row"
                              className="px-3 py-2 text-left font-normal text-ink-muted"
                            >
                              {metric.label}
                            </th>
                            {RAG_MODES.map((mode, index) => {
                              const result = response.results[mode]

                              return (
                                <td
                                  key={mode}
                                  className={cn(
                                    'tnum px-3 py-2 text-center',
                                    winner === index && 'font-medium text-accent',
                                  )}
                                >
                                  {result ? (
                                    metric.render(result)
                                  ) : (
                                    <Minus className="mx-auto h-3 w-3 text-ink-subtle" />
                                  )}
                                </td>
                              )
                            })}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>

            {/* Answers */}
            <div>
              <SectionHeading title="Answers" />
              <div className="space-y-3">
                {RAG_MODES.map((mode) => {
                  const result = response.results[mode]
                  if (!result) return null

                  const failed = result.debug?.error

                  return (
                    <Panel key={mode}>
                      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
                        <span className="text-sm font-medium capitalize">
                          {mode}
                        </span>
                        <span className="tnum text-xs text-ink-subtle">
                          {result.citations.length} citations ·{' '}
                          {result.retrieved_chunks.length} chunks ·{' '}
                          {formatLatency(result.latency_ms)}
                        </span>
                      </div>

                      <div className="px-3 py-2.5">
                        {failed ? (
                          <p className="text-sm text-danger">{String(failed)}</p>
                        ) : (
                          <p
                            className={cn(
                              'whitespace-pre-wrap text-sm leading-6',
                              result.answered ? 'text-ink' : 'text-ink-muted',
                            )}
                          >
                            {result.answer}
                          </p>
                        )}
                      </div>

                      {result.retrieved_chunks.length > 0 && (
                        <div className="border-t border-line">
                          <ModeEvidence result={result} />
                        </div>
                      )}
                    </Panel>
                  )
                })}
              </div>
            </div>

            {/* Per-mode traces */}
            <div>
              <SectionHeading title="Traces" />
              <div className="space-y-2">
                {RAG_MODES.map((mode) => {
                  const result = response.results[mode]
                  if (!result) return null

                  return (
                    <div key={mode}>
                      <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
                        {mode}
                      </p>
                      <RetrievalTrace result={result} />
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </PageBody>
    </>
  )
}
