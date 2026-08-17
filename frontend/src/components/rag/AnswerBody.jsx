import { Fragment } from 'react'

import { cn } from '@/lib/format'

/**
 * Renders a generated answer.
 *
 * Models format answers in Markdown — bold labels, bullet and numbered
 * lists, paragraphs — and rendering that as plain text showed the syntax
 * literally ("**Annual Leave**") and ran every list item into one block.
 *
 * This handles the small subset a grounded answer actually uses. It is a
 * hand-rolled parser rather than a Markdown library on purpose: citation
 * markers have to be interactive elements woven into the same inline pass,
 * and everything is emitted as React nodes, so no document text is ever
 * inserted as HTML.
 */

// Bold, italic, inline code, and a citation marker — one alternation so
// the pieces cannot overlap or swallow each other.
const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`]+`|\[\d+\])/g

const BULLET = /^\s*[-*+]\s+(.*)$/
const ORDERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

function CitationPill({ number, resolvable, active, onClick }) {
  return (
    <button
      type="button"
      disabled={!resolvable}
      onClick={() => onClick(number)}
      title={
        resolvable
          ? `Jump to source ${number}`
          : `Source ${number} was not returned with this answer`
      }
      className={cn(
        'mx-0.5 inline-flex h-[15px] min-w-[15px] items-center justify-center',
        'rounded-full px-1 align-super text-[10px] font-semibold leading-none',
        'tnum transition-colors',
        resolvable
          ? 'bg-accent/12 text-accent ring-1 ring-inset ring-accent/30 hover:bg-accent hover:text-white hover:ring-accent'
          : 'cursor-not-allowed text-ink-subtle ring-1 ring-inset ring-dashed ring-line-strong',
        resolvable && active && 'bg-accent text-white ring-accent',
      )}
    >
      {number}
    </button>
  )
}

/** Inline emphasis and citation markers within one line of text. */
function renderInline(text, context, keyPrefix) {
  const nodes = []
  let index = 0

  for (const piece of text.split(INLINE)) {
    if (!piece) continue

    const key = `${keyPrefix}-${index++}`

    if (/^\[\d+\]$/.test(piece)) {
      const number = Number(piece.slice(1, -1))

      nodes.push(
        <CitationPill
          key={key}
          number={number}
          resolvable={context.validNumbers.has(number)}
          active={context.activeNumber === number}
          onClick={context.onCitationClick}
        />,
      )
      continue
    }

    if (piece.startsWith('**') || piece.startsWith('__')) {
      nodes.push(
        <strong key={key} className="font-semibold text-ink">
          {piece.slice(2, -2)}
        </strong>,
      )
      continue
    }

    if (
      (piece.startsWith('*') && piece.endsWith('*')) ||
      (piece.startsWith('_') && piece.endsWith('_'))
    ) {
      nodes.push(<em key={key}>{piece.slice(1, -1)}</em>)
      continue
    }

    if (piece.startsWith('`')) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-raised px-1 py-0.5 font-mono text-[0.9em]"
        >
          {piece.slice(1, -1)}
        </code>,
      )
      continue
    }

    nodes.push(<Fragment key={key}>{piece}</Fragment>)
  }

  return nodes
}

/**
 * Group lines into paragraphs and lists.
 *
 * Line-based rather than split-on-blank-lines: list items are separated by
 * single newlines, so a blank-line split would fuse a whole list into one
 * paragraph — which is exactly how the syntax ended up on screen.
 */
function toBlocks(text) {
  const blocks = []
  let paragraph = []
  let list = null

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: 'p', lines: paragraph })
      paragraph = []
    }
  }

  const flushList = () => {
    if (list) {
      blocks.push(list)
      list = null
    }
  }

  for (const line of text.split('\n')) {
    if (!line.trim()) {
      flushParagraph()
      // An open list survives a blank line. Models routinely separate
      // items with one ("loose" list syntax), and closing on blank lines
      // turned a three-item list into three one-item lists.
      continue
    }

    const heading = line.match(HEADING)
    if (heading) {
      flushParagraph()
      flushList()
      blocks.push({ type: 'h', text: heading[1] })
      continue
    }

    const bullet = line.match(BULLET)
    const ordered = line.match(ORDERED)

    if (bullet || ordered) {
      const type = bullet ? 'ul' : 'ol'
      flushParagraph()

      if (!list || list.type !== type) {
        flushList()
        list = { type, items: [] }
      }

      list.items.push((bullet ?? ordered)[1])
      continue
    }

    flushList()
    paragraph.push(line)
  }

  flushParagraph()
  flushList()

  return blocks
}

export function AnswerBody({ text, validNumbers, activeNumber, onCitationClick }) {
  const context = { validNumbers, activeNumber, onCitationClick }
  const blocks = toBlocks(text)

  return (
    <div className="max-w-3xl space-y-3 text-base leading-7 text-ink">
      {blocks.map((block, index) => {
        if (block.type === 'h') {
          return (
            <p key={index} className="font-semibold text-ink">
              {renderInline(block.text, context, `h${index}`)}
            </p>
          )
        }

        if (block.type === 'ul' || block.type === 'ol') {
          const List = block.type === 'ul' ? 'ul' : 'ol'

          return (
            <List
              key={index}
              className={cn(
                'space-y-1 pl-5',
                // Markers render as list markers, so a "2." beside a
                // citation pill can no longer be mistaken for one.
                block.type === 'ul' ? 'list-disc' : 'list-decimal',
                'marker:text-ink-subtle',
              )}
            >
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex} className="pl-0.5">
                  {renderInline(item, context, `l${index}-${itemIndex}`)}
                </li>
              ))}
            </List>
          )
        }

        return (
          <p key={index}>
            {block.lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 && ' '}
                {renderInline(line, context, `p${index}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        )
      })}
    </div>
  )
}
