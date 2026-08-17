import { Fragment } from 'react'

import { cn } from '@/lib/format'

const CITATION = /\[(\d+)\]/g

/**
 * Renders an answer with its `[n]` markers as interactive citation pills.
 *
 * A marker pointing at a source that does not exist is rendered muted and
 * dashed rather than dropped: the generator already removes hallucinated
 * citations, so anything that reaches here and cannot resolve is worth
 * seeing, not hiding.
 */
export function AnswerBody({ text, validNumbers, activeNumber, onCitationClick }) {
  const nodes = []
  let lastIndex = 0
  let key = 0

  for (const match of text.matchAll(CITATION)) {
    const index = match.index ?? 0
    const number = Number(match[1])

    if (index > lastIndex) {
      nodes.push(
        <Fragment key={`t${key++}`}>{text.slice(lastIndex, index)}</Fragment>,
      )
    }

    const resolvable = validNumbers.has(number)

    nodes.push(
      <button
        key={`c${key++}`}
        type="button"
        disabled={!resolvable}
        onClick={() => onCitationClick(number)}
        title={
          resolvable
            ? `Jump to source ${number}`
            : `Source ${number} was not returned with this answer`
        }
        className={cn(
          'mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded px-1',
          'align-super text-[10px] font-semibold leading-none tnum transition-colors',
          resolvable
            ? 'border border-accent/25 bg-accent-soft text-accent hover:bg-accent hover:text-white'
            : 'cursor-not-allowed border border-dashed border-line-strong text-ink-subtle',
          resolvable && activeNumber === number && 'bg-accent text-white',
        )}
      >
        {number}
      </button>,
    )

    lastIndex = index + match[0].length
  }

  if (lastIndex < text.length) {
    nodes.push(<Fragment key={`t${key++}`}>{text.slice(lastIndex)}</Fragment>)
  }

  return (
    <p className="max-w-3xl whitespace-pre-wrap text-base leading-7 text-ink">
      {nodes}
    </p>
  )
}
