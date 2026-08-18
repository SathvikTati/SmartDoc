import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  CornerDownLeft,
  FileSearch,
  Loader2,
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
import { Panel } from '@/components/ui/Panel'
import { ErrorState, SkeletonBlock } from '@/components/ui/States'
import { InvestigationView } from '@/components/rag/InvestigationView'
import { QueryControls } from '@/components/rag/QueryControls'
import * as api from '@/lib/api'
import { FileIcon } from '@/components/FileIcon'
import { cn, formatCount, truncate } from '@/lib/format'
import { useDocuments } from '@/state/DocumentsContext'
import { useSettings } from '@/state/SettingsContext'
import { useInvestigations } from '@/state/InvestigationsContext'

/** "Monday afternoon" — a small orientation, not a fake personalisation. */
function greeting() {
  const now = new Date()
  const hour = now.getHours()

  const part = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening'

  return `${now.toLocaleDateString(undefined, { weekday: 'long' })} ${part}`
}

// Mirrors the max_length on AskRequest. Duplicated deliberately: the
// server stays authoritative, but reaching it just to be told "String
// should have at most 1000 characters" is a round trip and a raw
// validator message for something the box already knows.
const MAX_QUESTION = 1000

// Counting up from here rather than always — a counter on a six-word
// question is noise.
const COUNTER_FROM = 800

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
function isFollowUp(turn) {
  const conversation = turn.result?.metadata?.conversation ?? {}

  return (turn.relation ?? conversation.relation) === 'follow_up'
}

/**
 * The rule between two turns.
 *
 * A follow-up gets its label set into the line. A new topic has nothing
 * to label — and the line used to be split around the empty badge anyway,
 * leaving a gap in the middle that read as a rendering fault rather than
 * as a divider. It runs unbroken instead.
 */
function TurnDivider({ turn }) {
  if (!isFollowUp(turn)) {
    return <div className="mb-6 h-px bg-line" />
  }

  return (
    <div className="mb-6 flex items-center gap-3">
      <span className="h-px flex-1 bg-line" />
      <RelationBadge turn={turn} />
      <span className="h-px flex-1 bg-line" />
    </div>
  )
}

function RelationBadge({ turn }) {
  const conversation = turn.result?.metadata?.conversation ?? {}

  if (!isFollowUp(turn)) return null

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
  const { defaults } = useSettings()
  const {
    chats,
    loading: historyLoading,
    opening,
    current,
    appendTurn,
    startNew,
    error: historyError,
  } = useInvestigations()

  const [question, setQuestion] = useState('')
  // null means "whatever the defaults say", resolved server-side so an
  // API caller and the UI get the same treatment. Choosing one here
  // overrides it for this conversation only.
  const [mode, setMode] = useState(null)
  const [topK, setTopK] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [focused, setFocused] = useState(false)
  const [controlsOpen, setControlsOpen] = useState(false)
  const [scopeOpen, setScopeOpen] = useState(false)

  const abortRef = useRef(null)
  const inputRef = useRef(null)
  const lastTurnRef = useRef(null)
  const turnCountRef = useRef(0)

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

  const overLimit = question.length > MAX_QUESTION
  const canSubmit = question.trim().length > 0 && !overLimit && !running

  const turnCount = current?.turns?.length ?? 0

  // Bring the *new* turn to the top of the reading area.
  //
  // This used to scroll a sentinel at the end of the thread to `start`,
  // which pinned the bottom of the page to the top of the viewport and
  // left the answer above the fold — the thread looked cut in half. It
  // also ran in a requestAnimationFrame straight after the request, which
  // could fire before React had laid the new turn out.
  //
  // Keyed on the count instead, so it runs once the turn is on the page,
  // and only when one is added to a thread that already had turns —
  // scrolling the first answer of a conversation just moves it away.
  useEffect(() => {
    const grew = turnCount > turnCountRef.current && turnCountRef.current > 0

    turnCountRef.current = turnCount

    if (!grew) return

    lastTurnRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  }, [turnCount])

  async function run(text) {
    const trimmed = text?.trim()
    if (!trimmed || running) return

    // Checked here as well as on the controls, because Enter reaches this
    // without going through the button.
    if (trimmed.length > MAX_QUESTION) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setError(null)

    try {
      const result = await api.ask(trimmed, {
        mode: mode ?? defaults.mode,
        topK: topK ?? defaults.topK,
        documentIds: scopeIds,
        // Continuing the open conversation is what makes a follow-up
        // resolvable; without it every question starts from nothing.
        chatId: current?.id ?? null,
        signal: controller.signal,
      })

      appendTurn({
        id: result.metadata?.run_id ?? `local-${Date.now()}`,
        question: trimmed,
        mode: result.metadata?.mode,
        pipeline: result.metadata?.pipeline,
        topK: result.metadata?.top_k,
        result,
        askedAt: new Date().toISOString(),
      })

      setQuestion('')
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
        active={mode !== null || topK !== null}
        onClick={() => setControlsOpen((value) => !value)}
        title="Retrieval mode and how many chunks to retrieve"
      >
        <SlidersHorizontal className="h-3.5 w-3.5" />
        <span className="capitalize">{mode ?? defaults.mode}</span>
        <span className="text-ink-subtle">
          &middot; top {topK ?? defaults.topK}
        </span>
      </Pill>

      <PillButton
        className="ml-auto"
        loading={running}
        disabled={!canSubmit || !readyCount}
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
        mode={mode ?? defaults.mode}
        topK={topK ?? defaults.topK}
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
            if (canSubmit) void run(question)
          }
        }}
        placeholder={
          current
            ? 'Ask a follow-up — “what about sick leave?”, “who is eligible?”'
            : 'Ask about a policy, a control, a procedure…'
        }
        aria-label={current ? 'Follow-up question' : 'Question'}
        aria-invalid={overLimit || undefined}
        className="resize-none border-0 bg-transparent px-1 text-lg leading-7 shadow-none hover:border-0 focus:border-0"
      />

      {(overLimit || question.length >= COUNTER_FROM) && (
        <p
          className={cn(
            'px-1 pt-1 text-xs tnum',
            overLimit ? 'text-danger' : 'text-ink-subtle',
          )}
          role={overLimit ? 'alert' : undefined}
        >
          {overLimit
            ? `${question.length - MAX_QUESTION} characters over the ${MAX_QUESTION} limit — shorten the question to ask it.`
            : `${question.length} / ${MAX_QUESTION}`}
        </p>
      )}

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
                <div
                  key={turn.id ?? index}
                  ref={
                    index === current.turns.length - 1 ? lastTurnRef : null
                  }
                  className="scroll-mt-6"
                >
                  {index > 0 && <TurnDivider turn={turn} />}

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
          /* Centred in the available height rather than pinned near the
             top. With no conversation list under it there is nothing to
             fill the lower half, and a composer floating above a screen
             of empty canvas reads as a page that failed to load. */
          <div className="flex min-h-[70vh] flex-col justify-center">
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
      </PageBody>
    </>
  )
}
