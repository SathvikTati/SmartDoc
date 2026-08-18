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
 * Conversations and their turns, read from the server.
 *
 * A chat is the unit a follow-up resolves against, so the UI works in
 * chats rather than in isolated questions — but a chat is still a set of
 * discrete investigations, each with its own answer, sources and trace.
 * It is not a chat transcript: nothing is collapsed into a running stream.
 *
 * `chats`   — summaries for the sidebar and history
 * `current` — `{ id, title, turns[] }`, each turn a full stored result
 */
const InvestigationsContext = createContext(null)

const PAGE_SIZE = 50

export function InvestigationsProvider({ children }) {
  const [chats, setChats] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [current, setCurrent] = useState(null)
  const [opening, setOpening] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const page = await api.listChats({ limit: PAGE_SIZE })
      setChats(page.chats)
      setTotal(page.total)
      setError(null)
    } catch (caught) {
      setError(caught?.message ?? 'Could not load conversations')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  /**
   * Append a just-produced answer to the open chat.
   *
   * The result is already in hand, so this shows it immediately rather
   * than re-fetching the whole conversation.
   */
  const appendTurn = useCallback(
    (turn) => {
      setCurrent((existing) => {
        const chatId = turn.result?.metadata?.chat_id

        // A new chat, or a turn that belongs to the one already open.
        if (!existing || existing.id !== chatId) {
          return { id: chatId, title: turn.question, turns: [turn] }
        }

        return { ...existing, turns: [...existing.turns, turn] }
      })

      void refresh()
    },
    [refresh],
  )

  const open = useCallback(async (chatId) => {
    setOpening(true)
    setError(null)

    try {
      const chat = await api.getChat(chatId)

      setCurrent({
        id: chat.id,
        title: chat.title,
        turns: chat.turns.map((run) => ({
          id: run.id,
          question: run.question,
          mode: run.mode,
          topK: run.top_k,
          result: run.result,
          askedAt: run.created_at,
          relation: run.relation,
          standaloneQuestion: run.standalone_question,
          contextStrategy: run.context_strategy,
        })),
      })
    } catch (caught) {
      setError(caught?.message ?? 'Could not open that conversation')
    } finally {
      setOpening(false)
    }
  }, [])

  const remove = useCallback(
    async (chatId) => {
      // Optimistic: the row disappears at once, and a failed delete is
      // corrected by the refresh below.
      setChats((existing) => existing.filter((chat) => chat.id !== chatId))
      setCurrent((chat) => (chat?.id === chatId ? null : chat))

      try {
        await api.deleteChat(chatId)
      } catch (caught) {
        setError(caught?.message ?? 'Could not delete that conversation')
      }

      await refresh()
    },
    [refresh],
  )

  const value = useMemo(
    () => ({
      chats,
      total,
      loading,
      opening,
      error,
      current,
      appendTurn,
      open,
      startNew: () => setCurrent(null),
      remove,
      refresh,
    }),
    [
      chats,
      total,
      loading,
      opening,
      error,
      current,
      appendTurn,
      open,
      remove,
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
