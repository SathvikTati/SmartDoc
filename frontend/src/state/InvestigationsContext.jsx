import { createContext, useCallback, useContext, useMemo, useState } from 'react'

/**
 * One question and its result. Investigations are kept as a list of
 * independent records rather than a transcript: every question is its own
 * workspace, so nothing accumulates into an endless chat stream.
 *
 * Shape: { id, question, mode, topK, result, askedAt }
 */
const InvestigationsContext = createContext(null)

// Lives above the router so switching to Files and back does not discard
// the session's work.
export function InvestigationsProvider({ children }) {
  const [investigations, setInvestigations] = useState([])
  const [currentId, setCurrentId] = useState(null)

  const add = useCallback((investigation) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

    setInvestigations((current) => [
      { ...investigation, id, askedAt: Date.now() },
      ...current,
    ])
    setCurrentId(id)
  }, [])

  const remove = useCallback((id) => {
    setInvestigations((current) =>
      current.filter((investigation) => investigation.id !== id),
    )
    setCurrentId((current) => (current === id ? null : current))
  }, [])

  const value = useMemo(
    () => ({
      investigations,
      currentId,
      current:
        investigations.find((investigation) => investigation.id === currentId) ??
        null,
      add,
      open: setCurrentId,
      startNew: () => setCurrentId(null),
      remove,
      clear: () => {
        setInvestigations([])
        setCurrentId(null)
      },
    }),
    [investigations, currentId, add, remove],
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
