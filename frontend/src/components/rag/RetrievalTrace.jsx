import { Check, CircleSlash, Minus } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Disclosure } from '@/components/ui/Disclosure'
import { cn, formatLatency } from '@/lib/format'

/** Human labels for the pipeline node names the backend emits. */
const STAGE_LABELS = {
  semantic_search: 'Semantic search',
  document_selection: 'Document selection',
  section_selection: 'Section selection',
  chunk_retrieval: 'Chunk retrieval',
  hybrid_fusion: 'Hybrid fusion (RRF)',
  retrieval_planner: 'Retrieval planner',
  tool_execution: 'Tool execution',
  evidence_validation: 'Evidence validation',
  context_builder: 'Context builder',
  answer_generation: 'Answer generation',
}

function MatchTable({ title, matches, empty }) {
  return (
    <div className="min-w-0">
      <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
        {title}
      </h4>

      {matches.length === 0 ? (
        <p className="text-xs text-ink-subtle">{empty}</p>
      ) : (
        <ol className="space-y-1">
          {matches.slice(0, 8).map((match, index) => (
            <li
              key={`${match.chunk_id ?? match.filename}-${index}`}
              className="flex items-baseline gap-2 text-xs"
            >
              <span className="tnum w-4 shrink-0 text-ink-subtle">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-ink-muted">
                {match.filename}
                {match.section && (
                  <span className="text-ink-subtle"> · {match.section}</span>
                )}
              </span>
              {match.score != null && (
                <span className="tnum shrink-0 text-ink-subtle">
                  {match.score.toFixed(4)}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline gap-2 text-xs">
      <span className="w-28 shrink-0 text-ink-subtle">{label}</span>
      <span className="min-w-0 flex-1 text-ink-muted">{value}</span>
    </div>
  )
}

/**
 * The pipeline, as the backend reported it. Only surfaced values appear
 * here — tools chosen, counts, the one-line plan reason and the validation
 * verdict. The model's private reasoning is never exposed.
 */
export function RetrievalTrace({ result }) {
  const debug = result.debug ?? {}
  const metadata = result.metadata ?? {}
  const stages = debug.stages ?? []
  const validation = debug.validation_result ?? metadata.validation ?? null

  return (
    <Disclosure
      title="Retrieval trace"
      meta={`${result.retrieval_method.split(':')[0]} · ${formatLatency(result.latency_ms)}`}
    >
      <div className="space-y-5 p-3">
        {/* Pipeline */}
        <div>
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
            Pipeline
          </h4>

          <ol className="space-y-0">
            {stages.map((stage, index) => {
              const last = index === stages.length - 1
              const failed = stage.sufficient === false

              return (
                <li key={`${stage.name}-${index}`} className="flex gap-2.5">
                  <div className="flex w-4 flex-col items-center">
                    <span
                      className={cn(
                        'mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full',
                        failed ? 'bg-warn' : 'bg-accent',
                      )}
                    />
                    {!last && <span className="w-px flex-1 bg-line" />}
                  </div>

                  <div className={cn('min-w-0 flex-1', !last && 'pb-3')}>
                    <div className="flex flex-wrap items-center gap-x-2">
                      <span className="text-xs font-medium text-ink">
                        {STAGE_LABELS[stage.name] ?? stage.name}
                      </span>
                      {stage.results != null && (
                        <Badge tone="neutral">
                          <span className="tnum">{stage.results}</span>
                        </Badge>
                      )}
                      {stage.attempt != null && stage.attempt > 1 && (
                        <Badge tone="warn">Attempt {stage.attempt}</Badge>
                      )}
                      {stage.sufficient != null && (
                        <Badge tone={stage.sufficient ? 'ok' : 'warn'}>
                          {stage.sufficient ? (
                            <Check className="h-2.5 w-2.5" />
                          ) : (
                            <CircleSlash className="h-2.5 w-2.5" />
                          )}
                          {stage.sufficient ? 'Sufficient' : 'Insufficient'}
                        </Badge>
                      )}
                    </div>

                    {stage.detail && (
                      <p className="mt-0.5 text-xs text-ink-muted">
                        {stage.detail}
                      </p>
                    )}

                    {stage.tools?.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {stage.tools.map((tool) => (
                          <Badge key={tool} tone="accent">
                            {tool}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>

        {/* Agentic specifics */}
        {(debug.plan_reason || debug.tools_used || validation) && (
          <div className="space-y-1.5 border-t border-line pt-3">
            <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
              Agent
            </h4>

            {debug.plan_reason && (
              <Row label="Plan reason" value={debug.plan_reason} />
            )}

            {debug.tools_used?.length > 0 && (
              <Row
                label="Tools used"
                value={
                  <span className="flex flex-wrap gap-1">
                    {debug.tools_used.map((tool, index) => (
                      <Badge key={`${tool}-${index}`} tone="accent">
                        {tool}
                      </Badge>
                    ))}
                  </span>
                }
              />
            )}

            {metadata.attempts != null && (
              <Row
                label="Attempts"
                value={<span className="tnum">{metadata.attempts}</span>}
              />
            )}

            {validation && (
              <Row
                label="Validation"
                value={
                  <span className="flex flex-wrap items-baseline gap-1.5">
                    <Badge tone={validation.sufficient ? 'ok' : 'warn'}>
                      {validation.sufficient ? 'Sufficient' : 'Insufficient'}
                    </Badge>
                    <span>{validation.reason}</span>
                  </span>
                }
              />
            )}
          </div>
        )}

        {/* Hierarchical narrowing */}
        {(debug.retrieved_documents?.length > 0 ||
          debug.retrieved_sections?.length > 0) && (
          <div className="grid gap-5 border-t border-line pt-3 sm:grid-cols-2">
            <div className="min-w-0">
              <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
                Stage 1 · documents selected
              </h4>
              <ol className="space-y-1">
                {(debug.retrieved_documents ?? []).map((document) => (
                  <li
                    key={document.document_id}
                    className="flex items-baseline gap-2 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-ink-muted">
                      {document.filename}
                    </span>
                    <span className="tnum shrink-0 text-ink-subtle">
                      {document.score.toFixed(4)}
                    </span>
                  </li>
                ))}
              </ol>
              <p className="mt-1 text-2xs text-ink-subtle">
                BM25 over filenames and summaries in Postgres — the chunk
                index is not touched.
              </p>
            </div>

            <div className="min-w-0">
              <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
                Stage 2 · sections selected
              </h4>
              <ol className="space-y-1">
                {(debug.retrieved_sections ?? []).map((section, index) => (
                  <li
                    key={`${section.section_id}-${index}`}
                    className="flex items-baseline gap-2 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-ink-muted">
                      {section.section_path ||
                        section.section_title ||
                        section.filename ||
                        'unnamed section'}
                    </span>
                    {section.score != null && (
                      <span className="tnum shrink-0 text-ink-subtle">
                        {section.score.toFixed(4)}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}

        {/* Retriever comparison */}
        {(debug.semantic_matches?.length > 0 ||
          debug.keyword_matches?.length > 0) && (
          <div className="grid gap-5 border-t border-line pt-3 sm:grid-cols-2">
            <MatchTable
              title="Semantic matches"
              matches={debug.semantic_matches ?? []}
              empty="No semantic candidates."
            />
            <MatchTable
              title="Keyword matches (BM25)"
              matches={debug.keyword_matches ?? []}
              empty="No chunk shared a query term."
            />
          </div>
        )}

        {debug.matched_by_both?.length > 0 && (
          <div className="border-t border-line pt-3">
            <MatchTable
              title="Found by both retrievers"
              matches={debug.matched_by_both}
              empty="—"
            />
            <p className="mt-1 text-2xs text-ink-subtle">
              Agreement between the two retrievers is what RRF promotes to the
              top of the context.
            </p>
          </div>
        )}

        {debug.note && (
          <p className="flex items-start gap-1.5 border-t border-line pt-3 text-xs text-ink-subtle">
            <Minus className="mt-1 h-2.5 w-2.5 shrink-0" />
            {debug.note}
          </p>
        )}

        <div className="space-y-1.5 border-t border-line pt-3">
          <Row label="Method" value={result.retrieval_method} />
          <Row label="Latency" value={formatLatency(result.latency_ms)} />
          <Row
            label="Chunks in context"
            value={<span className="tnum">{result.retrieved_chunks.length}</span>}
          />
          <Row
            label="Citations"
            value={<span className="tnum">{result.citations.length}</span>}
          />
        </div>
      </div>
    </Disclosure>
  )
}
