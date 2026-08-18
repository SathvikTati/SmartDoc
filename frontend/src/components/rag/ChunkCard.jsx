import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, ExternalLink, Globe } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { FileIcon } from '@/components/FileIcon'
import { cn, scoreLabel } from '@/lib/format'

/** "hr_policy.md · Section 1.1 Annual Leave · Page 4" */
export function citationLabel(chunk) {
  const parts = [chunk.filename]

  if (chunk.section_title) parts.push(`Section ${chunk.section_title}`)
  if (chunk.page_number != null) parts.push(`Page ${chunk.page_number}`)

  return parts.join(' · ')
}

/** Which retrievers found this chunk, as small ticked labels. */
export function SourceTags({ chunk }) {
  if (!chunk.sources?.length) return null

  return (
    <>
      {chunk.sources.map((source) => (
        <Badge
          key={source}
          tone={chunk.sources.length > 1 ? 'ok' : 'neutral'}
          className="capitalize"
        >
          {source}
          {source === 'semantic' && chunk.semantic_rank != null && (
            <span className="tnum opacity-70">#{chunk.semantic_rank}</span>
          )}
          {source === 'keyword' && chunk.keyword_rank != null && (
            <span className="tnum opacity-70">#{chunk.keyword_rank}</span>
          )}
        </Badge>
      ))}
    </>
  )
}

export function ChunkScores({ chunk }) {
  return (
    <span className="tnum text-2xs text-ink-subtle">
      {chunk.score != null && (
        <>
          {scoreLabel(chunk.sources)} {chunk.score.toFixed(4)}
        </>
      )}
      {chunk.fused_score != null && <> · RRF {chunk.fused_score.toFixed(5)}</>}
    </span>
  )
}

export function ChunkCard({
  chunk,
  cited,
  expanded,
  highlighted,
  onToggle,
  anchorId,
}) {
  return (
    <div
      id={anchorId}
      className={cn(
        'scroll-mt-4 transition-colors',
        highlighted && 'bg-accent-soft/60',
      )}
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse chunk' : 'Expand chunk'}
          className="mt-0.5 rounded text-ink-subtle transition-colors hover:text-ink"
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </button>

        <span
          className={cn(
            'mt-0.5 flex h-4 min-w-4 items-center justify-center rounded px-1',
            'text-[10px] font-semibold leading-none tnum',
            cited
              ? 'bg-accent text-white'
              : 'border border-line bg-raised text-ink-subtle',
          )}
        >
          {chunk.number}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {chunk.url ? (
              <Globe className="h-3.5 w-3.5 shrink-0 text-warn" />
            ) : (
              <FileIcon filename={chunk.filename} className="h-3.5 w-3.5" />
            )}
            <span
              className={cn(
                'truncate text-sm',
                cited ? 'font-medium text-ink' : 'text-ink-muted',
              )}
            >
              {citationLabel(chunk)}
            </span>

            {/* A web result is not one of your documents, and an answer
                built on it means something different. Say so plainly. */}
            {chunk.url && <Badge tone="warn">Web</Badge>}
            {!cited && <Badge tone="neutral">Retrieved, unused</Badge>}
            <SourceTags chunk={chunk} />
          </div>

          <div className="mt-0.5 flex flex-wrap items-center gap-x-2">
            {chunk.section_path && (
              <span className="truncate text-2xs text-ink-subtle">
                {chunk.section_path}
              </span>
            )}
            <ChunkScores chunk={chunk} />
          </div>

          {expanded && (
            <div className="mt-2 animate-fade-in">
              <p className="whitespace-pre-wrap rounded border border-line bg-raised/60 p-2.5 text-xs leading-5 text-ink-muted">
                {chunk.content}
              </p>
              {chunk.url ? (
                // Never /files/… for a web chunk: there is no document
                // behind it, and the link would 404.
                <a
                  href={chunk.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-1.5 inline-flex max-w-full items-center gap-1 rounded text-2xs text-accent hover:underline"
                >
                  <span className="truncate">{chunk.url}</span>
                  <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                </a>
              ) : (
                <Link
                  to={`/files/${chunk.document_id}`}
                  className="mt-1.5 inline-flex items-center gap-1 rounded text-2xs text-accent hover:underline"
                >
                  Open {chunk.filename}
                  <ExternalLink className="h-2.5 w-2.5" />
                </Link>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
