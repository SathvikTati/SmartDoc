import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import * as api from '@/lib/api'
import { PENDING_STATUSES } from '@/lib/constants'

const ACTIVE_POLL_MS = 1_500
const IDLE_POLL_MS = 20_000

const DocumentsContext = createContext(null)

export function DocumentsProvider({ children }) {
  const [documents, setDocuments] = useState([])
  // True only for the very first load, so refreshes never blank the table.
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [apiOnline, setApiOnline] = useState(null)

  // Read inside the polling timeout without making it a dependency, which
  // would tear down and rebuild the timer on every single refresh.
  const documentsRef = useRef(documents)
  documentsRef.current = documents

  const refresh = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments())
      setError(null)
      setApiOnline(true)
    } catch (caught) {
      setError(caught?.message ?? 'Could not load documents')
      setApiOnline(false)
    } finally {
      setLoading(false)
    }
  }, [])

  const removeDocuments = useCallback(
    async (ids) => {
      // Sequential on purpose: each delete touches Postgres, the vector
      // store and the filesystem, and the API is a single local process.
      for (const id of ids) {
        await api.deleteDocument(id)
      }
      await refresh()
    },
    [refresh],
  )

  const ingesting = useMemo(
    () => documents.some((document) => PENDING_STATUSES.includes(document.status)),
    [documents],
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  // One self-rescheduling timeout rather than setInterval: the delay depends
  // on whether anything is ingesting, and a chain cannot overlap slow calls.
  useEffect(() => {
    let cancelled = false
    let timer

    const tick = async () => {
      await refresh()
      if (cancelled) return

      const pending = documentsRef.current.some((document) =>
        PENDING_STATUSES.includes(document.status),
      )

      timer = window.setTimeout(tick, pending ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    }

    timer = window.setTimeout(tick, ingesting ? ACTIVE_POLL_MS : IDLE_POLL_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [refresh, ingesting])

  const value = useMemo(
    () => ({
      documents,
      loading,
      error,
      apiOnline,
      ingesting,
      refresh,
      removeDocuments,
    }),
    [documents, loading, error, apiOnline, ingesting, refresh, removeDocuments],
  )

  return (
    <DocumentsContext.Provider value={value}>
      {children}
    </DocumentsContext.Provider>
  )
}

export function useDocuments() {
  const value = useContext(DocumentsContext)

  if (!value) {
    throw new Error('useDocuments must be used inside a DocumentsProvider')
  }

  return value
}
