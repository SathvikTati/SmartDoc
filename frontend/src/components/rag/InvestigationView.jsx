import { useMemo, useState } from 'react'
import {
  Check,
  Copy,
  GitCompareArrows,
  Globe,
  PlugZap,
  SearchX,
} from 'lucide-react'

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

/**
 * Copy the answer out.
 *
 * The answer is the thing people take somewhere else — into a ticket, an
 * email, a reply to whoever asked. Selecting it by hand drags in the
 * citation markers and the surrounding chrome, so it is offered as one
 * action.
 */
function CopyAnswer({ text }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // A denied clipboard permission is not worth an error state; the
      // text is on screen and selectable either way.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? 'Answer copied' : 'Copy answer'}
      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-ink-subtle transition-colors hover:bg-raised hover:text-ink"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-ok" />
          Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" />
          Copy
        </>
      )}
    </button>
  )
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

  // A calculation records the chunk_ids its figures came from. The reader
  // wants the [n] markers instead, so they can be found in the list above.
  const numberByChunkId = useMemo(() => {
    const lookup = new Map()

    for (const chunk of result.retrieved_chunks) {
      lookup.set(chunk.chunk_id, chunk.number)
    }

    return lookup
  }, [result.retrieved_chunks])

  const derivedNumbersFor = (chunk) =>
    (chunk.derived_from ?? [])
      .map((chunkId) => numberByChunkId.get(chunkId))
      .filter((number) => number != null)

  // An answer citing the web is a different claim from one citing only
  // the library, so it is stated rather than left to the source list.
  const webCitations = result.citations.filter((chunk) => chunk.url)

  const conflicts = result.metadata?.conflicts ?? []

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

  // A greeting is answered without retrieving, so the four evidence
  // panels below would all be empty. Showing them implies a search
  // happened and found nothing, which is not what occurred.
  if (result.metadata?.kind === 'smalltalk') {
    return (
      <div className="space-y-3">
        <p className="max-w-3xl border-l-2 border-accent/45 pl-3.5 text-[17px] font-medium leading-7 text-ink">
          {result.question}
        </p>
        <div className="max-w-3xl rounded-xl border border-line bg-surface px-4 py-3.5 shadow-panel">
          <p className="text-base leading-7 text-ink">{result.answer}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-7">
      {/* Question
          No "Question" label: the accent rule and the size already say
          what this is, and the label only added a full-width border two
          lines above the answer's. The badges sit on the question's own
          row instead of floating off at the far right of an empty one. */}
      <div className="flex items-start justify-between gap-4">
        <p className="min-w-0 max-w-3xl border-l-2 border-accent/45 pl-3.5 text-[17px] font-medium leading-7 text-ink">
          {result.question}
        </p>
        <div className="flex shrink-0 items-center gap-1.5 pt-1">
          <Badge tone="neutral">{MODE_LABELS[mode] ?? mode}</Badge>
          <Badge tone="neutral">
            <span className="tnum">{formatLatency(result.latency_ms)}</span>
          </Badge>
        </div>
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
          actions={
            result.answered && !providerError ? (
              <CopyAnswer text={result.answer} />
            ) : undefined
          }
        />

        {providerError ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-danger/25 bg-danger-soft px-3.5 py-3">
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
          /* The answer is what the page exists for, so it sits on its own
             surface with a hairline shadow. Full width, matching the
             panels below — the card used to stop short of them, leaving
             two ragged right edges down the page. AnswerBody keeps the
             prose itself at a readable measure. */
          <div className="rounded-xl border border-line bg-surface px-4 py-3.5 shadow-panel">
            <AnswerBody
              text={result.answer}
              validNumbers={citedNumbers}
              activeNumber={activeNumber}
              onCitationClick={revealCitation}
            />
          </div>
        ) : (
          <div className="flex items-start gap-2.5 rounded-xl border border-warn/25 bg-warn-soft px-3.5 py-3">
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

      {/* A figure was chosen over another. That is a judgement the reader
          should see, not something to leave buried in a sentence. */}
      {conflicts.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-warn/25 bg-warn-soft px-3.5 py-3">
          <GitCompareArrows className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">
              Your documents disagree
            </p>
            <p className="mt-0.5 text-sm text-ink-muted">
              Answered from the most recently uploaded. Delete the superseded
              document to remove the guesswork.
            </p>
            <ul className="mt-1.5 space-y-0.5">
              {conflicts.map((conflict) => (
                <li key={conflict} className="text-xs text-ink-subtle">
                  {conflict}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {webCitations.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-xl border border-warn/25 bg-warn-soft px-3.5 py-3">
          <Globe className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">
              This answer uses the web
            </p>
            <p className="mt-0.5 text-sm text-ink-muted">
              {webCitations.length} of {result.citations.length} cited sources
              came from the public internet, not from your documents. They are
              marked <span className="font-medium">Web</span> below.
            </p>
          </div>
        </div>
      )}

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
                derivedNumbers={derivedNumbersFor(chunk)}
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
                derivedNumbers={derivedNumbersFor(chunk)}
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
