import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import * as api from '@/lib/api'

/**
 * Query history, read from the server.
 *
 * It used to live in this component's state, which meant a refresh threw
 * away everything you had asked. The API stores each run with its full
 * result, so the list here is a view of that, and opening an old run
 * fetches exactly what it returned at the time.
 *
 * A run is `{ id, question, mode, top_k, answered, citation_count,
 * chunk_count, latency_ms, created_at }`; `result` arrives only on open.
 */
const InvestigationsContext = createContext(null)

const PAGE_SIZE = 50

export function InvestigationsProvider({ children }) {
  const [runs, setRuns] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // The run being viewed, with its full stored result.
  const [current, setCurrent] = useState(null)
  const [opening, setOpening] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const page = await api.listHistory({ limit: PAGE_SIZE })
      setRuns(page.runs)
      setTotal(page.total)
      setError(null)
    } catch (caught) {
      setError(caught?.message ?? 'Could not load history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  /**
   * Show a result that was just produced.
   *
   * The answer is already in hand, so this displays it immediately rather
   * than re-fetching it, and refreshes the list behind it.
   */
  const showResult = useCallback(
    (run) => {
      setCurrent(run)
      void refresh()
    },
    [refresh],
  )

  const open = useCallback(async (id) => {
    setOpening(true)
    setError(null)

    try {
      const run = await api.getHistoryRun(id)

      setCurrent({
        id: run.id,
        question: run.question,
        mode: run.mode,
        topK: run.top_k,
        result: run.result,
        askedAt: run.created_at,
        promptVersions: run.prompt_versions,
      })
    } catch (caught) {
      setError(caught?.message ?? 'Could not open that question')
    } finally {
      setOpening(false)
    }
  }, [])

  const remove = useCallback(
    async (id) => {
      // Optimistic: the row disappears immediately, and a failed delete
      // is corrected by the refresh below.
      setRuns((existing) => existing.filter((run) => run.id !== id))
      setCurrent((run) => (run?.id === id ? null : run))

      try {
        await api.deleteHistoryRun(id)
      } catch (caught) {
        setError(caught?.message ?? 'Could not delete that question')
      }

      await refresh()
    },
    [refresh],
  )

  const clear = useCallback(async () => {
    try {
      await api.clearHistory()
      setCurrent(null)
    } catch (caught) {
      setError(caught?.message ?? 'Could not clear history')
    }

    await refresh()
  }, [refresh])

  const value = useMemo(
    () => ({
      runs,
      total,
      loading,
      opening,
      error,
      current,
      showResult,
      open,
      startNew: () => setCurrent(null),
      remove,
      clear,
      refresh,
    }),
    [
      runs,
      total,
      loading,
      opening,
      error,
      current,
      showResult,
      open,
      remove,
      clear,
      refresh,
    ],
  )

  return (
    <InvestigationsContext.Provider value={value}>
      {children}
    </InvestigationsContext.Provider>
  )
}

export function useInvestigations() {
  const value = useContext(InvestigationsContext)

  if (!value) {
    throw new Error(
      'useInvestigations must be used inside an InvestigationsProvider',
    )
  }

  return value
}
