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
 * What a pipeline can be built from, and the defaults a new chat uses.
 *
 * A chat's default is a *mode* — naive, hybrid or agentic. Choosing
 * between the strategies inside a family is what the Pipelines page is
 * for; putting seven options behind a chat setting would make the common
 * case worse to serve the rare one. The catalogue is still loaded here
 * because that page and the composer both read it.
 *
 * Both live on the server rather than in this browser. A default that
 * only existed in localStorage would be a different default on a
 * colleague's machine and would disappear on a cache clear, which is the
 * wrong behaviour for something described as *the* default. It also means
 * a question asked over the API with no pipeline named gets the same
 * treatment as one asked through the UI.
 *
 * The catalogue is fetched once. Retrievers and tools are declared in
 * code, so they cannot change without a restart.
 */
const SettingsContext = createContext(null)

const DEFAULT_MODE_KEY = 'defaults.mode'
const DEFAULT_TOP_K_KEY = 'defaults.top_k'

export function SettingsProvider({ children }) {
  const [options, setOptions] = useState({
    retrievers: [],
    tools: [],
    presets: [],
  })
  const [defaults, setDefaults] = useState({ mode: 'hybrid', topK: 5 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)

    try {
      const [catalogue, settings] = await Promise.all([
        api.listRetrievalOptions(),
        api.listSettings(),
      ])

      setOptions(catalogue)

      const byKey = new Map(settings.map((row) => [row.key, row.value]))

      setDefaults({
        mode: byKey.get(DEFAULT_MODE_KEY) ?? 'hybrid',
        topK: Number(byKey.get(DEFAULT_TOP_K_KEY) ?? 5),
      })

      setError(null)
    } catch (caught) {
      // The app still works without these: the server applies its own
      // defaults when a request names neither.
      setError(caught?.message ?? 'Could not load settings')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** Persist both, then adopt them. Written server-side, so they hold. */
  const saveDefaults = useCallback(async ({ mode, topK }) => {
    await Promise.all([
      api.updateSetting(DEFAULT_MODE_KEY, mode),
      api.updateSetting(DEFAULT_TOP_K_KEY, Number(topK)),
    ])

    setDefaults({ mode, topK: Number(topK) })
  }, [])

  const value = useMemo(
    () => ({
      options,
      defaults,
      loading,
      error,
      saveDefaults,
      reload: load,
    }),
    [options, defaults, loading, error, saveDefaults, load],
  )

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const value = useContext(SettingsContext)

  if (!value) {
    throw new Error('useSettings must be used inside a SettingsProvider')
  }

  return value
}
