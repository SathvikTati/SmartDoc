import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CornerDownLeft,
  FileSearch,
  MessageSquareText,
  Plus,
  Upload,
  X,
} from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Field'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import { InvestigationView } from '@/components/rag/InvestigationView'
import { QueryControls } from '@/components/rag/QueryControls'
import * as api from '@/lib/api'
import { cn, formatLatency, formatRelative, truncate } from '@/lib/format'
import { useDocuments } from '@/state/DocumentsContext'
import { useInvestigations } from '@/state/InvestigationsContext'

const EXAMPLES = [
  'How much annual leave do employees get?',
  'What is control SEC-4412?',
  'What is the grievance procedure?',
]

export function AskPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { documents, loading: documentsLoading } = useDocuments()
  const { investigations, current, add, open, startNew, remove } =
    useInvestigations()

  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [topK, setTopK] = useState(5)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const abortRef = useRef(null)
  const inputRef = useRef(null)

  // Arriving from a document's "Ask about this document" action.
  const scopedTo = searchParams.get('document')

  const readyCount = documents.filter(
    (document) => document.status === 'READY',
  ).length

  useEffect(() => {
    if (!current && !running) inputRef.current?.focus()
  }, [current, running])

  async function run(text) {
    const trimmed = text?.trim()
    if (!trimmed || running) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setError(null)

    try {
      const result = await api.ask(trimmed, mode, topK, controller.signal)
      add({ question: trimmed, mode, topK, result })
      setQuestion('')
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught?.message ?? 'The query failed')
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  function newQuestion() {
    startNew()
    setQuestion('')
    setError(null)
    // Focus lands after the composer mounts.
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  const composer = (
    <div className="space-y-3">
      {scopedTo && (
        <div className="flex items-start gap-2 rounded-md border border-line bg-raised/60 px-3 py-2">
          <FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-subtle" />
          <p className="min-w-0 flex-1 text-xs text-ink-muted">
            Starting from <span className="font-medium">{scopedTo}</span>.
            Retrieval always searches the whole library, so naming the document
            in your question is what steers it there.
          </p>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setSearchParams({}, { replace: true })}
            className="rounded text-ink-subtle hover:text-ink"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="relative">
        <Textarea
          ref={inputRef}
          rows={3}
          value={question}
          disabled={running}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            // Enter submits; Shift+Enter adds a line. The box is short
            // because these are questions, not documents.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void run(question)
            }
          }}
          placeholder="Ask a question about your document library…"
          aria-label="Question"
          className="pr-28"
        />
        <div className="absolute bottom-2 right-2">
          <Button
            variant="primary"
            loading={running}
            disabled={!question.trim() || !readyCount}
            onClick={() => void run(question)}
          >
            {!running && <CornerDownLeft className="h-3.5 w-3.5" />}
            {running ? 'Retrieving…' : 'Ask'}
          </Button>
        </div>
      </div>

      <QueryControls
        mode={mode}
        topK={topK}
        onModeChange={setMode}
        onTopKChange={setTopK}
        disabled={running}
      />

      {!documentsLoading && readyCount === 0 && (
        <div className="flex items-center justify-between gap-3 rounded-md border border-line bg-raised/60 px-3 py-2">
          <p className="text-xs text-ink-muted">
            No documents are ready yet, so there is nothing to retrieve from.
          </p>
          <Link to="/files">
            <Button size="sm">
              <Upload className="h-3.5 w-3.5" />
              Upload
            </Button>
          </Link>
        </div>
      )}

      {!current && readyCount > 0 && investigations.length === 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-xs text-ink-subtle">Try:</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuestion(example)
                inputRef.current?.focus()
              }}
              className="rounded border border-line px-2 py-0.5 text-xs text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
            >
              {example}
            </button>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <>
      <Header
        crumbs={[{ label: 'Ask' }]}
        actions={
          current && (
            <Button size="sm" variant="primary" onClick={newQuestion}>
              <Plus className="h-3.5 w-3.5" />
              New question
            </Button>
          )
        }
      />

      <PageBody>
        <div className="mb-5">
          <h1 className="text-lg font-semibold tracking-tight">
            {current ? 'Current investigation' : 'Start an investigation'}
          </h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            {current
              ? 'Each question is its own workspace. Start a new one rather than stacking follow-ups.'
              : 'Ask a question about your document library and get a cited answer.'}
          </p>
        </div>

        {error && (
          <ErrorState
            title="Query failed"
            message={error}
            className="mb-5"
            onRetry={() => void run(current?.question ?? question)}
          />
        )}

        {running && !current && (
          <Panel className="mb-5 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm text-ink-muted">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              Retrieving and generating — a local model can take a few seconds.
            </div>
            <SkeletonBlock lines={4} />
          </Panel>
        )}

        {current ? (
          <>
            <InvestigationView result={current.result} mode={current.mode} />

            <div className="mt-8 flex justify-center border-t border-line pt-6">
              <Button variant="primary" onClick={newQuestion}>
                <Plus className="h-3.5 w-3.5" />
                New question
              </Button>
            </div>
          </>
        ) : (
          composer
        )}

        {/* Recent investigations */}
        {investigations.length > 0 && (
          <div className="mt-10">
            <SectionHeading
              title="Recent investigations"
              meta={`${investigations.length} this session`}
            />

            <Panel className="divide-y divide-line">
              {investigations.map((investigation) => {
                const active = investigation.id === current?.id

                return (
                  <div
                    key={investigation.id}
                    className={cn(
                      'group flex items-center gap-3 px-3 py-2 transition-colors',
                      active ? 'bg-accent-soft/50' : 'hover:bg-raised/70',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => open(investigation.id)}
                      className="min-w-0 flex-1 rounded text-left"
                    >
                      <p
                        className={cn(
                          'truncate text-sm text-ink',
                          active && 'font-medium',
                        )}
                      >
                        {truncate(investigation.question, 110)}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-subtle">
                        <span className="capitalize">{investigation.mode}</span>
                        <span>·</span>
                        <span className="tnum">
                          {investigation.result.citations.length} source
                          {investigation.result.citations.length === 1 ? '' : 's'}
                        </span>
                        <span>·</span>
                        <span className="tnum">
                          {formatLatency(investigation.result.latency_ms)}
                        </span>
                        <span>·</span>
                        <span>
                          {formatRelative(
                            new Date(investigation.askedAt).toISOString(),
                          )}
                        </span>
                      </p>
                    </button>

                    {!investigation.result.answered && (
                      <Badge tone="warn">Unanswered</Badge>
                    )}

                    <button
                      type="button"
                      aria-label="Remove investigation"
                      onClick={() => remove(investigation.id)}
                      className="rounded p-1 text-ink-subtle opacity-0 transition-opacity hover:bg-raised hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </Panel>

            {current && (
              <div className="mt-3 flex justify-center">
                <Button onClick={newQuestion}>
                  <Plus className="h-3.5 w-3.5" />
                  New question
                </Button>
              </div>
            )}
          </div>
        )}

        {!current && !running && investigations.length === 0 && readyCount > 0 && (
          <EmptyState
            icon={MessageSquareText}
            title="No investigations yet"
            description="Answers, their citations and the full retrieval trace will appear here."
            className="mt-4"
          />
        )}
      </PageBody>
    </>
  )
}
