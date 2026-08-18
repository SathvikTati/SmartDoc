import { useMemo, useRef, useState } from 'react'
import { Check, Loader2, Play, Plus, RotateCcw, X } from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { AnswerBody } from '@/components/rag/AnswerBody'
import { ChunkCard } from '@/components/rag/ChunkCard'
import {
  CompositionBuilder,
  describe,
} from '@/components/rag/CompositionBuilder'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Disclosure } from '@/components/ui/Disclosure'
import { Select, Textarea } from '@/components/ui/Field'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { ErrorState, SkeletonBlock } from '@/components/ui/States'
import * as api from '@/lib/api'
import { cn, formatLatency } from '@/lib/format'
import { useSettings } from '@/state/SettingsContext'

const MAX_QUESTION = 1000

// Two is the smallest comparison that says anything; past four the wait
// is long enough that people stop reading the results.
const MIN_PIPELINES = 2
const MAX_PIPELINES = 4

const TOP_K_OPTIONS = [3, 5, 8, 10, 15, 20].map((value) => ({
  value: String(value),
  label: String(value),
}))

/**
 * Questions that separate the strategies rather than flatter them.
 *
 * A comparison where every pipeline returns the same answer teaches
 * nothing. Each of these is one a particular retriever gets wrong.
 */
const PROBES = [
  {
    label: 'Exact code',
    question: 'What does SEC-1177 cover?',
    note: 'Keyword finds it; semantic alone has no neighbourhood to search.',
  },
  {
    label: 'Paraphrase',
    question: 'Can I work from another country for a while?',
    note: 'Semantic finds it; the document shares almost none of these words.',
  },
  {
    label: 'Deep section',
    question: 'How is part-time annual leave calculated?',
    note: 'Three heading levels down in a long document.',
  },
  {
    label: 'Across documents',
    question: 'What does each document say about probation?',
    note: 'Every pipeline switches to coverage — watch how many documents each thinks qualify.',
  },
  {
    label: 'Arithmetic',
    question: 'I have taken 8 days of leave. How many do I have remaining?',
    note: 'The sum runs after retrieval either way; the agent can also ask for it.',
  },
]

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
  { label: 'Citations', render: (result) => result.citations?.length ?? 0 },
  {
    label: 'Chunks retrieved',
    render: (result) => result.retrieved_chunks?.length ?? 0,
  },
  {
    label: 'Documents drawn on',
    render: (result) =>
      new Set((result.citations ?? []).map((chunk) => chunk.filename)).size,
  },
  {
    label: 'Documents covered',
    render: (result) => {
      if (!result.metadata?.aggregated) return '—'

      const covered = result.metadata.documents_covered?.length ?? 0
      const matched = result.metadata.documents_matched ?? covered

      return matched > covered ? `${covered} of ${matched}` : covered
    },
    onlyWhenAggregated: true,
  },
  {
    label: 'Tools used',
    render: (result) => result.metadata?.tools_used?.join(', ') || '—',
    onlyWhenAgent: true,
  },
  {
    label: 'Latency',
    render: (result) => formatLatency(result.latency_ms),
    lowerIsBetter: true,
  },
]

const BLANK = { retrievers: ['semantic'], agent: false, planner: true, tools: [] }

export function PipelinesPage() {
  const { options, defaults, loading, error: settingsError } = useSettings()

  const [question, setQuestion] = useState('')
  const [topK, setTopK] = useState(defaults.topK)
  const [response, setResponse] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(new Set())

  // Two to start: one dense retriever against one sparse. They are the
  // pair that differ most, so the first run teaches something.
  const [configurations, setConfigurations] = useState([
    { retrievers: ['semantic'], agent: false, planner: true, tools: [] },
    { retrievers: ['keyword'], agent: false, planner: true, tools: [] },
  ])

  const abortRef = useRef(null)
  const inputRef = useRef(null)

  const overLimit = question.length > MAX_QUESTION

  const allValid = configurations.every((one) => one.retrievers.length > 0)

  const canRun =
    question.trim().length > 0 &&
    !overLimit &&
    !running &&
    allValid &&
    configurations.length >= MIN_PIPELINES

  function update(index, next) {
    setConfigurations((current) =>
      current.map((one, position) => (position === index ? next : one)),
    )
  }

  function add() {
    if (configurations.length >= MAX_PIPELINES) return
    setConfigurations((current) => [...current, { ...BLANK }])
  }

  function remove(index) {
    setConfigurations((current) =>
      current.filter((_, position) => position !== index),
    )
  }

  /** A preset fills the builder in — it is a shortcut, not a mode. */
  function applyPreset(preset) {
    setConfigurations([
      {
        retrievers: [...preset.retrievers],
        agent: preset.agent,
        planner: preset.planner,
        tools: [...(preset.extra_tools ?? [])],
      },
      ...configurations.slice(1),
    ])
  }

  function toggleChunk(key) {
    setExpanded((current) => {
      const next = new Set(current)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  async function run() {
    if (!canRun) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setError(null)
    setResponse(null)

    try {
      setResponse(
        await api.compare(question.trim(), {
          configurations,
          topK,
          signal: controller.signal,
        }),
      )
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught?.message ?? 'The comparison failed')
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  const results = response?.results ?? null
  const ran = results ? Object.keys(results) : []

  const anyAggregated =
    !!results &&
    Object.values(results).some((one) => one?.metadata?.aggregated)

  const anyAgent =
    !!results && Object.values(results).some((one) => one?.metadata?.agent)

  // Breadth wanted more than the budget allowed. Never left silent: a
  // coverage answer that quietly dropped four documents reads as though
  // it had covered everything.
  const anyTruncated =
    !!results &&
    Object.values(results).some(
      (one) => (one?.metadata?.documents_dropped_for_budget ?? 0) > 0,
    )

  // Fastest that actually answered. Not "the winner" — a fast wrong
  // answer is not a win — but it is the number people look for.
  const fastest = useMemo(() => {
    if (!results) return null

    const answered = Object.entries(results).filter(([, one]) => one?.answered)

    if (answered.length === 0) return null

    return answered.reduce((best, current) =>
      (current[1].latency_ms ?? Infinity) < (best[1].latency_ms ?? Infinity)
        ? current
        : best,
    )[0]
  }, [results])

  const visibleMetrics = METRICS.filter(
    (metric) =>
      (!metric.onlyWhenAggregated || anyAggregated) &&
      (!metric.onlyWhenAgent || anyAgent),
  )

  return (
    <>
      <Header
        crumbs={[{ label: 'Pipelines' }]}
        actions={
          response && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setResponse(null)
                setError(null)
                inputRef.current?.focus()
              }}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Clear
            </Button>
          )
        }
      />

      <PageBody>
        <div className="mb-4">
          <h1 className="text-lg font-semibold tracking-tight">
            Build a pipeline and test it
          </h1>
          <p className="mt-0.5 max-w-3xl text-sm text-ink-muted">
            Pick the retrievers, decide whether an agent sits on top, and
            run the same question through two to four of them. The agent
            can only plan over the retrievers you gave it, so switching it
            on compares one variable rather than two.
          </p>
        </div>

        {settingsError && (
          <ErrorState message={settingsError} className="mb-4" />
        )}

        {loading ? (
          <Panel className="p-4">
            <SkeletonBlock lines={4} />
          </Panel>
        ) : (
          <>
            <Panel className="mb-5 p-4">
              <Textarea
                ref={inputRef}
                rows={2}
                value={question}
                disabled={running}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    if (canRun) void run()
                  }
                }}
                placeholder="Ask the same question of every pipeline…"
                aria-label="Question"
                aria-invalid={overLimit || undefined}
                className="resize-none border-0 bg-transparent px-1 text-base leading-7 shadow-none hover:border-0 focus:border-0"
              />

              {overLimit && (
                <p className="tnum px-1 pb-1 text-xs text-danger" role="alert">
                  {question.length - MAX_QUESTION} characters over the{' '}
                  {MAX_QUESTION} limit.
                </p>
              )}

              {!response && !running && (
                <div className="mb-3 flex flex-wrap gap-1.5 px-1">
                  {PROBES.map((probe) => (
                    <button
                      key={probe.label}
                      type="button"
                      title={probe.note}
                      onClick={() => {
                        setQuestion(probe.question)
                        inputRef.current?.focus()
                      }}
                      className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-muted transition-colors hover:bg-raised hover:text-ink"
                    >
                      {probe.label}
                    </button>
                  ))}
                </div>
              )}

              {/* Presets fill the first slot in — swatches, not modes. */}
              <div className="mb-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
                <span className="text-2xs font-medium uppercase tracking-wide text-ink-subtle">
                  Start from
                </span>
                {(options.presets ?? []).map((preset) => (
                  <button
                    key={preset.name}
                    type="button"
                    disabled={running}
                    onClick={() => applyPreset(preset)}
                    title={preset.method}
                    className="rounded-full border border-line px-2.5 py-1 text-xs text-ink-muted transition-colors hover:bg-raised hover:text-ink"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {configurations.map((one, index) => (
                  <CompositionBuilder
                    key={index}
                    index={index}
                    value={one}
                    options={options}
                    disabled={running}
                    onChange={(next) => update(index, next)}
                    onRemove={
                      configurations.length > MIN_PIPELINES
                        ? () => remove(index)
                        : undefined
                    }
                  />
                ))}
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-3">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={add}
                  disabled={running || configurations.length >= MAX_PIPELINES}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add pipeline
                </Button>

                <label
                  className="flex items-center gap-1.5 text-xs text-ink-muted"
                  title="The chunk budget. A library-wide question spends it across documents rather than on the best chunks overall."
                >
                  Top K
                  <Select
                    value={String(topK)}
                    disabled={running}
                    onChange={(event) => setTopK(Number(event.target.value))}
                    options={TOP_K_OPTIONS}
                    className="w-16"
                  />
                </label>

                <span className="text-xs text-ink-subtle">
                  runs one at a time
                </span>

                <Button
                  className="ml-auto"
                  size="sm"
                  variant="primary"
                  disabled={!canRun}
                  onClick={() => void run()}
                >
                  {running ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Running
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5" />
                      Run {configurations.length}
                    </>
                  )}
                </Button>
              </div>
            </Panel>

            {error && <ErrorState message={error} className="mb-4" />}

            {running && (
              <Panel className="p-4">
                <div className="mb-3 flex items-center gap-2 text-sm text-ink-muted">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  Running {configurations.length} pipelines in sequence…
                </div>
                <SkeletonBlock lines={4} />
              </Panel>
            )}

            {results && (
              <div className="space-y-5">
                <div>
                  <SectionHeading title="At a glance" meta={response.question} />
                  <Panel className="overflow-x-auto">
                    <table className="w-full border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-line">
                          <th
                            scope="col"
                            className="px-3 py-2 text-left text-2xs font-medium uppercase tracking-wide text-ink-subtle"
                          >
                            Metric
                          </th>
                          {ran.map((id) => (
                            <th
                              key={id}
                              scope="col"
                              className="px-3 py-2 text-center text-xs font-medium text-ink"
                            >
                              {results[id]?.metadata?.pipeline_label ?? id}
                              <span className="mt-0.5 block font-mono text-2xs font-normal text-ink-subtle">
                                {id}
                              </span>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {visibleMetrics.map((metric) => (
                          <tr
                            key={metric.label}
                            className="border-b border-line last:border-0"
                          >
                            <th
                              scope="row"
                              className="px-3 py-2 text-left text-xs font-normal text-ink-muted"
                            >
                              {metric.label}
                            </th>
                            {ran.map((id) => (
                              <td
                                key={id}
                                className={cn(
                                  'tnum px-3 py-2 text-center text-sm',
                                  metric.lowerIsBetter &&
                                    id === fastest &&
                                    'font-medium text-ok',
                                )}
                              >
                                {results[id] ? metric.render(results[id]) : '—'}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Panel>

                  {anyAggregated && (
                    <p className="mt-2 px-1 text-xs leading-5 text-ink-muted">
                      This is a question about the library as a whole, so
                      every pipeline switched to <strong>coverage</strong>{' '}
                      retrieval — best chunks from each matching document
                      rather than the best overall. Top K still bounds the
                      total; it is spent on breadth instead of depth. A
                      pipeline with no keyword signal has nothing to decide
                      which documents genuinely mention the topic, so it
                      matches more of them.
                    </p>
                  )}

                  {anyTruncated && (
                    <p className="mt-1.5 px-1 text-xs leading-5 text-warn">
                      Top K was too small to cover every matching document,
                      so the weakest were dropped — that is what{' '}
                      <span className="tnum">n of m</span> means above.
                      Raise it to see them.
                    </p>
                  )}
                </div>

                <div>
                  <SectionHeading
                    title="Answers"
                    meta="same question, same prompt — only the pipeline differed"
                  />

                  <div className="grid gap-3 md:grid-cols-2">
                    {ran.map((id) => {
                      const result = results[id]
                      if (!result) return null

                      const cited = new Set(
                        (result.citations ?? []).map((chunk) => chunk.number),
                      )

                      return (
                        <Panel key={id} className="flex flex-col">
                          <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
                            <span className="truncate text-sm font-medium text-ink">
                              {result.metadata?.pipeline_label ?? id}
                            </span>
                            <span className="flex shrink-0 items-center gap-1.5 text-xs text-ink-subtle">
                              {result.metadata?.agent && (
                                <Badge tone="neutral">agent</Badge>
                              )}
                              {result.metadata?.aggregated && (
                                <Badge tone="neutral">coverage</Badge>
                              )}
                              <span className="tnum">
                                {formatLatency(result.latency_ms)}
                              </span>
                            </span>
                          </div>

                          <div className="flex-1 px-3 py-2.5">
                            {result.answered ? (
                              <AnswerBody
                                text={result.answer}
                                validNumbers={cited}
                              />
                            ) : (
                              <p className="text-sm leading-6 text-ink-muted">
                                {result.answer}
                              </p>
                            )}
                          </div>

                          <p className="px-3 pb-2 text-2xs text-ink-subtle">
                            {result.retrieval_method}
                          </p>

                          <div className="border-t border-line">
                            <Disclosure
                              title="Evidence"
                              meta={`${result.retrieved_chunks?.length ?? 0} chunks`}
                            >
                              <div className="divide-y divide-line">
                                {(result.retrieved_chunks ?? []).map((chunk) => (
                                  <ChunkCard
                                    key={`${id}:${chunk.chunk_id}`}
                                    chunk={chunk}
                                    cited={cited.has(chunk.number)}
                                    expanded={expanded.has(
                                      `${id}:${chunk.chunk_id}`,
                                    )}
                                    onToggle={() =>
                                      toggleChunk(`${id}:${chunk.chunk_id}`)
                                    }
                                  />
                                ))}

                                {(result.retrieved_chunks ?? []).length ===
                                  0 && (
                                  <p className="px-3 py-3 text-sm text-ink-subtle">
                                    Nothing was retrieved.
                                  </p>
                                )}
                              </div>
                            </Disclosure>
                          </div>
                        </Panel>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}

            {!results && !running && !error && (
              <p className="px-1 text-sm text-ink-subtle">
                Currently comparing{' '}
                {configurations.map(describe).join('  ·  ')}. The probes
                above are chosen to separate pipelines rather than flatter
                them — each is one a particular retriever gets wrong.
              </p>
            )}
          </>
        )}
      </PageBody>
    </>
  )
}
