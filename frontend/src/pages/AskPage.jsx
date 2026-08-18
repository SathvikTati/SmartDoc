import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CornerDownLeft,
  FileSearch,
  Loader2,
  MessageSquareText,
  Plus,
  Reply,
  SlidersHorizontal,
  Upload,
  X,
} from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Field'
import { Pill, PillButton } from '@/components/ui/Pill'
import { Panel, SectionHeading } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import { InvestigationView } from '@/components/rag/InvestigationView'
import { QueryControls } from '@/components/rag/QueryControls'
import * as api from '@/lib/api'
import { FileIcon } from '@/components/FileIcon'
import { cn, formatCount, formatRelative, truncate } from '@/lib/format'
import { useDocuments } from '@/state/DocumentsContext'
import { useInvestigations } from '@/state/InvestigationsContext'

/** "Monday afternoon" — a small orientation, not a fake personalisation. */
function greeting() {
  const now = new Date()
  const hour = now.getHours()

  const part = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'

  return `${now.toLocaleDateString(undefined, { weekday: 'long' })} ${part}`
}

// Ask is a working surface, so it shows only the last few conversations.
// The full record lives on /history.
const RECENT_SHOWN = 5

const EXAMPLES = [
  'How much annual leave do employees get?',
  'What is control SEC-4412?',
  'Which documents mention probation?',
]

/**
 * How a turn was read in context.
 *
 * Only shown for a follow-up: a new topic is the normal case and saying so
 * on every turn would be noise. Seeing *when* prior context was applied is
 * the point — it is the difference between an answer about sick leave and
 * one that quietly inherited maternity leave.
 */
function RelationBadge({ turn }) {
  const conversation = turn.result?.metadata?.conversation ?? {}
  const relation = turn.relation ?? conversation.relation

  if (relation !== 'follow_up') return null

  const rewritten = turn.standaloneQuestion ?? conversation.standalone_question
  const strategy = turn.contextStrategy ?? conversation.strategy

  return (
    <span className="flex items-center gap-1.5">
      <Badge tone="accent">
        <Reply className="h-2.5 w-2.5" />
        Follow-up
      </Badge>

      {strategy === 'reuse' && <Badge tone="neutral">reused sources</Badge>}

      {rewritten && (
        <span
          className="max-w-[320px] truncate text-2xs text-ink-subtle"
          title={rewritten}
        >
          searched as “{rewritten}”
        </span>
      )}
    </span>
  )
}

export function AskPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { documents, loading: documentsLoading } = useDocuments()
  const {
    chats,
    total,
    loading: historyLoading,
    opening,
    current,
    appendTurn,
    open,
    startNew,
    remove,
    error: historyError,
  } = useInvestigations()

  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [topK, setTopK] = useState(5)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [focused, setFocused] = useState(false)
  const [controlsOpen, setControlsOpen] = useState(false)
  const [scopeOpen, setScopeOpen] = useState(false)

  const abortRef = useRef(null)
  const inputRef = useRef(null)
  const threadEndRef = useRef(null)

  // Arriving from a document's "Ask about…" action. `docs` is a hard
  // scope: retrieval cannot reach outside it in any mode.
  const scopeIds = useMemo(
    () => (searchParams.get('docs') ?? '').split(',').filter(Boolean),
    [searchParams],
  )

  const scopedDocuments = useMemo(
    () => documents.filter((document) => scopeIds.includes(document.id)),
    [documents, scopeIds],
  )

  function dropFromScope(id) {
    const remaining = scopeIds.filter((value) => value !== id)
    setSearchParams(remaining.length ? { docs: remaining.join(',') } : {}, {
      replace: true,
    })
  }

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
      const result = await api.ask(
        trimmed,
        mode,
        topK,
        scopeIds,
        // Continuing the open conversation is what makes a follow-up
        // resolvable; without it every question starts from nothing.
        current?.id ?? null,
        controller.signal,
      )

      appendTurn({
        id: result.metadata?.run_id ?? `local-${Date.now()}`,
        question: trimmed,
        mode,
        topK,
        result,
        askedAt: new Date().toISOString(),
      })

      setQuestion('')

      window.requestAnimationFrame(() =>
        threadEndRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        }),
      )
    } catch (caught) {
      if (controller.signal.aborted) return
      setError(caught?.message ?? 'The query failed')
    } finally {
      if (!controller.signal.aborted) setRunning(false)
    }
  }

  function newConversation() {
    startNew()
    setQuestion('')
    setError(null)
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  const scopePanel = (scopeOpen || scopeIds.length > 0) && (
    <div className="mt-3 border-t border-line pt-3 animate-fade-in">
      {scopeIds.length === 0 ? (
        <p className="text-xs text-ink-subtle">
          Retrieval searches every ready document. To narrow it, select files
          in{' '}
          <Link to="/files" className="text-accent hover:underline">
            Files
          </Link>{' '}
          and choose “Ask about these documents”.
        </p>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-ink-muted">
              Nothing outside these can be retrieved or cited.
            </p>
            <button
              type="button"
              onClick={() => setSearchParams({}, { replace: true })}
              className="rounded text-xs text-ink-muted transition-colors hover:text-ink"
            >
              Search everything
            </button>
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {scopedDocuments.map((document) => (
              <span
                key={document.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-raised/60 py-1 pl-2 pr-1.5 text-xs"
              >
                <FileIcon filename={document.filename} className="h-3 w-3" />
                <span className="max-w-[200px] truncate">
                  {document.filename}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${document.filename} from the scope`}
                  onClick={() => dropFromScope(document.id)}
                  className="rounded-full p-0.5 text-ink-subtle transition-colors hover:bg-line hover:text-ink"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}

            {scopeIds.length > scopedDocuments.length && (
              <span className="self-center text-xs text-ink-subtle">
                {scopeIds.length - scopedDocuments.length} no longer in the
                library
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )

  const controlPills = (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Pill
        active={scopeIds.length > 0}
        onClick={() => setScopeOpen((value) => !value)}
        title="Restrict retrieval to specific documents"
      >
        <FileSearch className="h-3.5 w-3.5" />
        {scopeIds.length > 0
          ? `Scope: ${formatCount(scopeIds.length, 'document')}`
          : 'Scope: whole library'}
      </Pill>

      <Pill
        active={mode !== 'hybrid'}
        onClick={() => setControlsOpen((value) => !value)}
        title="Retrieval mode and how many chunks to retrieve"
      >
        <SlidersHorizontal className="h-3.5 w-3.5" />
        <span className="capitalize">{mode}</span>
        <span className="text-ink-subtle">&middot; top {topK}</span>
      </Pill>

      <PillButton
        className="ml-auto"
        loading={running}
        disabled={!question.trim() || !readyCount}
        onClick={() => void run(question)}
      >
        {running ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Retrieving…
          </>
        ) : current ? (
          <>
            <CornerDownLeft className="h-3.5 w-3.5" />
            Follow up
          </>
        ) : (
          'Get answers'
        )}
      </PillButton>
    </div>
  )

  const modeControls = controlsOpen && (
    <div className="mt-3 border-t border-line pt-3 animate-fade-in">
      <QueryControls
        mode={mode}
        topK={topK}
        onModeChange={setMode}
        onTopKChange={setTopK}
        disabled={running}
      />
    </div>
  )

  const composerCard = (
    <div
      className={cn(
        'rounded-2xl border bg-surface p-4 transition-shadow',
        focused ? 'border-line-strong shadow-pop' : 'border-line shadow-panel',
      )}
    >
      <Textarea
        ref={inputRef}
        rows={2}
        value={question}
        disabled={running}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            void run(question)
          }
        }}
        placeholder={
          current
            ? 'Ask a follow-up — “what about sick leave?”, “who is eligible?”'
            : 'Ask about a policy, a control, a procedure…'
        }
        aria-label={current ? 'Follow-up question' : 'Question'}
        className="resize-none border-0 bg-transparent px-1 text-lg leading-7 shadow-none hover:border-0 focus:border-0"
      />

      {controlPills}
      {modeControls}
      {scopePanel}
    </div>
  )

  return (
    <>
      <Header
        crumbs={[{ label: 'Ask' }]}
        actions={
          current && (
            <Button size="sm" variant="primary" onClick={newConversation}>
              <Plus className="h-3.5 w-3.5" />
              New conversation
            </Button>
          )
        }
      />

      <PageBody>
        {current && (
          <div className="mb-6">
            <h1 className="text-lg font-semibold tracking-tight">
              {truncate(current.title, 90)}
            </h1>
            <p className="mt-0.5 text-sm text-ink-muted">
              {formatCount(current.turns.length, 'question')} in this
              conversation. Each keeps its own answer, sources and trace — a
              follow-up is resolved against the ones before it.
            </p>
          </div>
        )}

        {error && (
          <ErrorState
            title="Query failed"
            message={error}
            className="mb-5"
            onRetry={() => void run(question)}
          />
        )}

        {historyError && (
          <ErrorState
            title="Conversations unavailable"
            message={historyError}
            className="mb-5"
          />
        )}

        {opening && (
          <Panel className="mb-5 p-4">
            <SkeletonBlock lines={3} />
          </Panel>
        )}

        {current ? (
          <>
            <div className="space-y-10">
              {current.turns.map((turn, index) => (
                <div key={turn.id ?? index}>
                  {index > 0 && (
                    <div className="mb-6 flex items-center gap-3">
                      <span className="h-px flex-1 bg-line" />
                      <RelationBadge turn={turn} />
                      <span className="h-px flex-1 bg-line" />
                    </div>
                  )}

                  <InvestigationView
                    result={turn.result}
                    mode={turn.mode ?? turn.result?.metadata?.mode}
                  />
                </div>
              ))}
            </div>

            {running && (
              <Panel className="mt-8 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm text-ink-muted">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  Resolving against the conversation, then retrieving…
                </div>
                <SkeletonBlock lines={3} />
              </Panel>
            )}

            <div ref={threadEndRef} />

            <div className="mt-8 border-t border-line pt-6">
              {composerCard}
              <p className="mt-2 text-xs text-ink-subtle">
                A follow-up is read in the context of this conversation. An
                unrelated question starts fresh rather than inheriting it.
              </p>
            </div>
          </>
        ) : running ? (
          <Panel className="p-4">
            <div className="mb-3 flex items-center gap-2 text-sm text-ink-muted">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              Retrieving and generating — a local model can take a few seconds.
            </div>
            <SkeletonBlock lines={4} />
          </Panel>
        ) : (
          <div className="pt-[8vh]">
            <div className="mx-auto w-full max-w-3xl">
              <p className="text-lg text-ink-subtle">{greeting()}</p>
              <h1 className="mt-1 font-display text-display text-ink">
                What do you need to know?
              </h1>

              <div className="mt-7">{composerCard}</div>

              {readyCount > 0 && chats.length === 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {EXAMPLES.map((example) => (
                    <Pill
                      key={example}
                      onClick={() => {
                        setQuestion(example)
                        inputRef.current?.focus()
                      }}
                    >
                      {example}
                    </Pill>
                  ))}
                </div>
              )}

              {!documentsLoading && readyCount === 0 && (
                <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-3">
                  <p className="text-sm text-ink-muted">
                    No documents are ready yet, so there is nothing to retrieve
                    from.
                  </p>
                  <Link to="/files">
                    <Button size="sm">
                      <Upload className="h-3.5 w-3.5" />
                      Upload
                    </Button>
                  </Link>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Recent conversations */}
        {chats.length > 0 && (
          <div className="mt-10">
            <SectionHeading
              title="Recent conversations"
              meta={`${Math.min(RECENT_SHOWN, total)} of ${total}`}
              actions={
                total > RECENT_SHOWN && (
                  <Link
                    to="/history"
                    className="rounded text-xs text-accent transition-colors hover:underline"
                  >
                    View all →
                  </Link>
                )
              }
            />

            <Panel className="divide-y divide-line">
              {chats.slice(0, RECENT_SHOWN).map((chat) => {
                const active = chat.id === current?.id

                return (
                  <div
                    key={chat.id}
                    className={cn(
                      'group flex items-center gap-3 px-3 py-2 transition-colors',
                      active ? 'bg-accent-soft/50' : 'hover:bg-raised/70',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => void open(chat.id)}
                      className="min-w-0 flex-1 rounded text-left"
                    >
                      <p
                        className={cn(
                          'truncate text-sm text-ink',
                          active && 'font-medium',
                        )}
                      >
                        {truncate(chat.title, 110)}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-subtle">
                        <span className="tnum">
                          {formatCount(chat.turn_count, 'question')}
                        </span>
                        <span>·</span>
                        <span>{formatRelative(chat.updated_at)}</span>
                      </p>
                    </button>

                    <button
                      type="button"
                      aria-label="Delete conversation"
                      onClick={() => void remove(chat.id)}
                      className="rounded p-1 text-ink-subtle opacity-0 transition-opacity hover:bg-raised hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </Panel>
          </div>
        )}

        {!current &&
          !running &&
          !historyLoading &&
          chats.length === 0 &&
          readyCount > 0 && (
            <EmptyState
              icon={MessageSquareText}
              title="No conversations yet"
              description="Answers, their citations and the full retrieval trace are saved here and survive a refresh."
              className="mt-4"
            />
          )}
      </PageBody>
    </>
  )
}
