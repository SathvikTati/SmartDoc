import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ChevronLeft,
  ChevronRight,
  MessageSquareText,
  Trash2,
  X,
} from 'lucide-react'

import { Header } from '@/components/layout/Header'
import { PageBody } from '@/components/layout/AppLayout'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Field'
import { Panel } from '@/components/ui/Panel'
import { EmptyState, ErrorState, SkeletonBlock } from '@/components/ui/States'
import * as api from '@/lib/api'
import { cn, formatDateTime, formatLatency, formatRelative } from '@/lib/format'
import { useInvestigations } from '@/state/InvestigationsContext'

const PAGE_SIZE = 25

/**
 * Every question ever asked, not just the recent few.
 *
 * Ask and the sidebar show a short list because they are working surfaces;
 * this is the full record, paged from the server rather than held in
 * memory, so it stays usable once there are hundreds of runs.
 */
export function HistoryPage() {
  const navigate = useNavigate()
  const { open, refresh: refreshRecent } = useInvestigations()

  const [page, setPage] = useState({ runs: [], total: 0 })
  const [offset, setOffset] = useState(0)
  const [mode, setMode] = useState('all')
  const [answered, setAnswered] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const runs = await api.listHistory({
        limit: PAGE_SIZE,
        offset,
        mode: mode === 'all' ? undefined : mode,
        answered: answered === 'all' ? undefined : answered === 'yes',
      })

      setPage(runs)
    } catch (caught) {
      setError(caught?.message ?? 'Could not load history')
    } finally {
      setLoading(false)
    }
  }, [offset, mode, answered])

  useEffect(() => {
    void load()
  }, [load])

  // A filter change invalidates the current page position.
  function changeFilter(setter) {
    return (event) => {
      setter(event.target.value)
      setOffset(0)
    }
  }

  async function openRun(run) {
    // Opening from history restores the whole conversation the question
    // belonged to, not the question alone — a follow-up is meaningless
    // without the turns around it.
    if (!run.chat_id) return
    await open(run.chat_id)
    navigate('/ask')
  }

  async function removeRun(id) {
    try {
      await api.deleteHistoryRun(id)
      await load()
      await refreshRecent()
    } catch (caught) {
      setError(caught?.message ?? 'Could not delete that question')
    }
  }

  async function clearAll() {
    const confirmed = window.confirm(
      `Delete all ${page.total} saved questions? This cannot be undone.`,
    )
    if (!confirmed) return

    try {
      await api.clearHistory()
      setOffset(0)
      await load()
      await refreshRecent()
    } catch (caught) {
      setError(caught?.message ?? 'Could not clear history')
    }
  }

  const filtering = mode !== 'all' || answered !== 'all'
  const lastPage = offset + PAGE_SIZE >= page.total

  return (
    <>
      <Header
        crumbs={[{ label: 'Ask', to: '/ask' }, { label: 'History' }]}
        actions={
          page.total > 0 && (
            <Button size="sm" variant="danger" onClick={() => void clearAll()}>
              <Trash2 className="h-3.5 w-3.5" />
              Clear all
            </Button>
          )
        }
      />

      <PageBody>
        <div className="mb-5">
          <h1 className="text-lg font-semibold tracking-tight">
            Question history
          </h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            Every question is saved with the answer, citations and retrieval
            trace it produced. Opening one restores exactly what was shown.
          </p>
        </div>

        {error && (
          <ErrorState
            title="Could not load history"
            message={error}
            onRetry={() => void load()}
            className="mb-4"
          />
        )}

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select
            aria-label="Filter by mode"
            value={mode}
            onChange={changeFilter(setMode)}
            className="w-36"
            options={[
              { value: 'all', label: 'All modes' },
              { value: 'naive', label: 'Naive' },
              { value: 'hybrid', label: 'Hybrid' },
              { value: 'agentic', label: 'Agentic' },
            ]}
          />

          <Select
            aria-label="Filter by outcome"
            value={answered}
            onChange={changeFilter(setAnswered)}
            className="w-40"
            options={[
              { value: 'all', label: 'All outcomes' },
              { value: 'yes', label: 'Answered' },
              { value: 'no', label: 'Unanswered' },
            ]}
          />

          {filtering && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setMode('all')
                setAnswered('all')
                setOffset(0)
              }}
            >
              Clear
            </Button>
          )}

          <span className="ml-auto tnum text-xs text-ink-subtle">
            {page.total === 0
              ? 'nothing saved'
              : `${offset + 1}–${Math.min(offset + PAGE_SIZE, page.total)} of ${page.total}`}
          </span>
        </div>

        {loading ? (
          <Panel className="p-4">
            <SkeletonBlock lines={6} />
          </Panel>
        ) : page.runs.length === 0 ? (
          <Panel>
            <EmptyState
              icon={MessageSquareText}
              title={filtering ? 'No questions match' : 'No questions yet'}
              description={
                filtering
                  ? 'Try a different mode or outcome.'
                  : 'Answers you get on Ask are saved here automatically.'
              }
              action={
                <Link to="/ask">
                  <Button variant="primary">Ask a question</Button>
                </Link>
              }
            />
          </Panel>
        ) : (
          <Panel className="divide-y divide-line">
            {page.runs.map((run) => (
              <div
                key={run.id}
                className="group flex items-center gap-3 px-3 py-2.5 transition-colors hover:bg-raised/70"
              >
                <button
                  type="button"
                  onClick={() => void openRun(run)}
                  className="min-w-0 flex-1 rounded text-left"
                >
                  <p className="truncate text-sm text-ink">{run.question}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-subtle">
                    <span className="capitalize">{run.mode}</span>
                    <span>·</span>
                    <span className="tnum">
                      {run.citation_count} source
                      {run.citation_count === 1 ? '' : 's'}
                    </span>
                    <span>·</span>
                    <span className="tnum">{run.chunk_count} chunks</span>
                    <span>·</span>
                    <span className="tnum">{formatLatency(run.latency_ms)}</span>
                    <span>·</span>
                    <span title={formatDateTime(run.created_at)}>
                      {formatRelative(run.created_at)}
                    </span>
                  </p>
                </button>

                {!run.answered && <Badge tone="warn">Unanswered</Badge>}

                <button
                  type="button"
                  aria-label="Delete this question"
                  onClick={() => void removeRun(run.id)}
                  className={cn(
                    'rounded p-1 text-ink-subtle opacity-0 transition-opacity',
                    'hover:bg-raised hover:text-ink',
                    'group-hover:opacity-100 focus-visible:opacity-100',
                  )}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </Panel>
        )}

        {page.total > PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-between">
            <Button
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Newer
            </Button>

            <Button
              size="sm"
              disabled={lastPage}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </PageBody>
    </>
  )
}
