import { useMemo, useState } from 'react'
import { PlugZap, SearchX } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Disclosure } from '@/components/ui/Disclosure'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { AnswerBody } from './AnswerBody'
import { ChunkCard } from './ChunkCard'
import { RetrievalTrace } from './RetrievalTrace'
import { formatLatency } from '@/lib/format'

const MODE_LABELS = {
  naive: 'Naive',
  hybrid: 'Hybrid',
  agentic: 'Agentic',
}

export function InvestigationView({ result, mode }) {
  const [activeNumber, setActiveNumber] = useState(null)

  // An expired key or a stopped model server is an operator problem with
  // an obvious fix, and it looks nothing like "no answer in the library".
  const providerError =
    result.metadata?.provider_error ?? result.debug?.provider_error ?? null

  const [expanded, setExpanded] = useState(new Set())

  const citedNumbers = useMemo(
    () => new Set(result.citations.map((chunk) => chunk.number)),
    [result.citations],
  )

  function toggle(chunkId) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(chunkId)) next.delete(chunkId)
      else next.add(chunkId)
      return next
    })
  }

  function revealCitation(number) {
    const chunk = result.citations.find((item) => item.number === number)
    if (!chunk) return

    setActiveNumber(number)
    setExpanded((current) => new Set(current).add(chunk.chunk_id))

    // Let the expansion render before scrolling to it.
    window.requestAnimationFrame(() => {
      document
        .getElementById(`source-${number}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }

  const unused = result.retrieved_chunks.filter(
    (chunk) => !citedNumbers.has(chunk.number),
  )

  return (
    <div className="space-y-7">
      {/* Question */}
      <div>
        <SectionHeading
          title="Question"
          actions={
            <div className="flex items-center gap-1.5">
              <Badge tone="neutral">{MODE_LABELS[mode] ?? mode}</Badge>
              <Badge tone="neutral">
                <span className="tnum">{formatLatency(result.latency_ms)}</span>
              </Badge>
            </div>
          }
        />
        <p className="max-w-3xl text-base font-medium leading-6 text-ink">
          {result.question}
        </p>
      </div>

      {/* Answer */}
      <div>
        <SectionHeading
          title="Answer"
          meta={
            result.answered
              ? `${result.citations.length} citation${result.citations.length === 1 ? '' : 's'}`
              : undefined
          }
        />

        {providerError ? (
          <div className="flex max-w-3xl items-start gap-2.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5">
            <PlugZap className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">
                The model provider could not answer
              </p>
              <p className="mt-0.5 text-sm text-ink-muted">
                {providerError.message}
              </p>
              <p className="mt-1.5 text-xs text-ink-subtle">
                {providerError.retryable
                  ? 'This usually clears on its own — try again in a moment.'
                  : 'This will not fix itself; check the model settings in .env.'}
              </p>
            </div>
          </div>
        ) : result.answered ? (
          <AnswerBody
            text={result.answer}
            validNumbers={citedNumbers}
            activeNumber={activeNumber}
            onCitationClick={revealCitation}
          />
        ) : (
          <div className="flex max-w-3xl items-start gap-2.5 rounded-md border border-warn/25 bg-warn-soft px-3 py-2.5">
            <SearchX className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            <div>
              <p className="text-sm font-medium text-ink">
                No answer in the library
              </p>
              <p className="mt-0.5 text-sm text-ink-muted">{result.answer}</p>
            </div>
          </div>
        )}
      </div>

      {/* Sources */}
      {result.citations.length > 0 && (
        <div>
          <SectionHeading title="Sources" meta="cited by the answer" />
          <Panel className="divide-y divide-line">
            {result.citations.map((chunk) => (
              <ChunkCard
                key={chunk.chunk_id}
                chunk={chunk}
                cited
                anchorId={`source-${chunk.number}`}
                highlighted={activeNumber === chunk.number}
                expanded={expanded.has(chunk.chunk_id)}
                onToggle={() => toggle(chunk.chunk_id)}
              />
            ))}
          </Panel>
        </div>
      )}

      {/* Evidence */}
      <div className="space-y-3">
        <Disclosure
          title="Retrieved evidence"
          meta={`${result.retrieved_chunks.length} chunk${
            result.retrieved_chunks.length === 1 ? '' : 's'
          } retrieved · ${unused.length} unused`}
        >
          <div className="divide-y divide-line">
            {result.retrieved_chunks.map((chunk) => (
              <ChunkCard
                key={chunk.chunk_id}
                chunk={chunk}
                cited={citedNumbers.has(chunk.number)}
                expanded={expanded.has(chunk.chunk_id)}
                onToggle={() => toggle(chunk.chunk_id)}
              />
            ))}

            {result.retrieved_chunks.length === 0 && (
              <p className="px-3 py-4 text-sm text-ink-subtle">
                Nothing was retrieved for this question.
              </p>
            )}
          </div>
        </Disclosure>

        <RetrievalTrace result={result} />
      </div>
    </div>
  )
}
