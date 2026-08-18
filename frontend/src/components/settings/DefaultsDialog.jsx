import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Loader2, X } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Label, SegmentedControl, Select } from '@/components/ui/Field'
import { MODE_OPTIONS } from '@/components/rag/QueryControls'
import { useSettings } from '@/state/SettingsContext'
import { cn } from '@/lib/format'

const TOP_K_CHOICES = [3, 5, 8, 10, 15, 20]

/**
 * The defaults a new chat starts with.
 *
 * A mode, not a pipeline. Chats stay on the three families; picking
 * between the strategies inside one is a retrieval question, and the
 * Pipelines page is where you can actually answer it by running both.
 *
 * Deliberately two fields. Everything else that could be configured here
 * — prompts, thresholds, the aggregation knobs — is reachable through the
 * settings API and belongs to whoever is tuning the system, not to
 * whoever is asking it questions. These two are the ones a person changes
 * because they prefer a different answer, not a different system.
 *
 * Saved server-side. A default that lived in this browser would be a
 * different default on another machine, and would not apply to a question
 * asked over the API.
 */
export function DefaultsDialog({ open, onClose }) {
  const { defaults, saveDefaults } = useSettings()

  const dialogRef = useRef(null)

  // null means "whatever is saved". Seeding state from `defaults`
  // instead would capture whatever it was on first render — and the
  // settings load asynchronously, so on a cold open that is null, and
  // the select would show its first option as though it were the
  // default. Deriving keeps the two in step without an effect to sync
  // them.
  const [mode, setMode] = useState(null)
  const [topK, setTopK] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const selectedMode = mode ?? defaults.mode
  const selectedTopK = topK ?? defaults.topK

  // Reopening should show what is currently in force, not whatever was
  // half-selected last time and abandoned.
  useEffect(() => {
    if (!open) return

    setMode(null)
    setTopK(null)
    setSaved(false)
    setError(null)

    dialogRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return

    function onKeyDown(event) {
      if (event.key === 'Escape' && !saving) onClose()
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, saving, onClose])

  if (!open) return null

  const dirty =
    selectedMode !== defaults.mode || selectedTopK !== defaults.topK

  async function save() {
    setSaving(true)
    setError(null)

    try {
      await saveDefaults({ mode: selectedMode, topK: selectedTopK })
      setSaved(true)
      setTimeout(onClose, 700)
    } catch (caught) {
      setError(caught?.message ?? 'Could not save the defaults')
    } finally {
      setSaving(false)
    }
  }

  const chosen = MODE_OPTIONS.find((one) => one.value === selectedMode)

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/20 p-4 pt-[8vh] animate-fade-in"
      onClick={(event) => {
        if (event.target === event.currentTarget && !saving) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Chat defaults"
        tabIndex={-1}
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border border-line bg-surface shadow-pop animate-slide-up"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium">Chat defaults</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            aria-label="Close"
            className="rounded p-1 text-ink-subtle transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <p className="mb-4 text-xs leading-5 text-ink-subtle">
            Applied to every new conversation. An individual question can
            still override them from the composer, and this does not change
            answers already given.
          </p>

          <p className="mb-4 text-xs leading-5 text-ink-subtle">
            To compare the individual retrieval strategies inside a mode —
            semantic against keyword, or hierarchical against flat — use{' '}
            <Link
              to="/pipelines"
              onClick={onClose}
              className="rounded text-accent hover:underline"
            >
              Pipelines
            </Link>
            .
          </p>

          <div className="space-y-4">
            <div>
              <Label>Retrieval mode</Label>
              <div className="mt-1">
                <SegmentedControl
                  name="default-mode"
                  value={selectedMode}
                  options={MODE_OPTIONS}
                  onChange={setMode}
                />
              </div>

              {chosen && (
                <p className="mt-1.5 text-xs leading-5 text-ink-muted">
                  {chosen.hint}
                </p>
              )}
            </div>

            <div>
              <Label htmlFor="default-top-k">Chunks to retrieve</Label>
              <Select
                id="default-top-k"
                value={selectedTopK}
                onChange={(event) => setTopK(Number(event.target.value))}
                className="mt-1 w-full"
              >
                {TOP_K_CHOICES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
              <p className="mt-1.5 text-xs leading-5 text-ink-muted">
                More is not always better. Past a point the extra chunks are
                near-misses that dilute the context the answer is written
                from.
              </p>
            </div>
          </div>

          {error && (
            <p className="mt-4 rounded border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line px-4 py-3">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={() => void save()}
            disabled={saving || !dirty || !selectedMode}
            className={cn(saved && 'pointer-events-none')}
          >
            {saving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Saving
              </>
            ) : saved ? (
              <>
                <Check className="h-3.5 w-3.5" />
                Saved
              </>
            ) : (
              'Save defaults'
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
