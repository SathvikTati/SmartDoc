import { Bot, Wrench } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/format'

/**
 * One pipeline, composed.
 *
 * Retrievers on the left, an agent switch, and — only once the agent is
 * on — the tools it may reach for. The order matters: the tools are
 * meaningless without an agent to use them, so they appear when they
 * start mattering rather than sitting greyed out.
 *
 * The agent never widens retrieval. Its retrieval tools come from the
 * checkboxes above it, which is what makes "with agent" against "without
 * agent" a comparison of one variable.
 */
export function CompositionBuilder({
  value,
  options,
  disabled,
  onChange,
  onRemove,
  index,
}) {
  const { retrievers = [], tools = [] } = options

  function toggleRetriever(id) {
    const next = value.retrievers.includes(id)
      ? value.retrievers.filter((one) => one !== id)
      : [...value.retrievers, id]

    onChange({ ...value, retrievers: next })
  }

  function toggleTool(id) {
    const current = value.tools ?? []

    onChange({
      ...value,
      tools: current.includes(id)
        ? current.filter((one) => one !== id)
        : [...current, id],
    })
  }

  const empty = value.retrievers.length === 0

  return (
    <div
      className={cn(
        'rounded-xl border p-3',
        empty ? 'border-warn/40 bg-warn-soft/30' : 'border-line bg-surface',
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-2xs font-medium uppercase tracking-wide text-ink-subtle">
          Pipeline {index + 1}
        </span>

        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            disabled={disabled}
            className="rounded px-1.5 py-0.5 text-xs text-ink-subtle transition-colors hover:bg-raised hover:text-ink"
          >
            Remove
          </button>
        )}
      </div>

      {/* Retrievers */}
      <div className="flex flex-wrap gap-1.5">
        {retrievers.map((one) => {
          const on = value.retrievers.includes(one.id)

          return (
            <button
              key={one.id}
              type="button"
              onClick={() => toggleRetriever(one.id)}
              disabled={disabled}
              aria-pressed={on}
              title={one.description}
              className={cn(
                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                on
                  ? 'border-accent/50 bg-accent-soft text-ink'
                  : 'border-line text-ink-muted hover:bg-raised hover:text-ink',
              )}
            >
              {one.label}
            </button>
          )
        })}
      </div>

      {empty && (
        <p className="mt-1.5 text-xs text-warn">
          Pick at least one retriever — there is nothing to search with
          otherwise.
        </p>
      )}

      {/* Agent */}
      <label className="mt-2.5 flex cursor-pointer items-center gap-2 border-t border-line pt-2.5 text-sm">
        <input
          type="checkbox"
          checked={value.agent}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, agent: event.target.checked })
          }
          className="h-3.5 w-3.5 rounded border-line-strong text-accent focus-visible:ring-accent/40"
        />
        <Bot className="h-3.5 w-3.5 text-ink-subtle" />
        <span className="text-ink">Agent</span>
        <span className="text-xs text-ink-subtle">
          plans, validates, retries once
        </span>
      </label>

      {value.agent && (
        <div className="mt-2 space-y-2 rounded-lg bg-raised/60 p-2.5 animate-fade-in">
          <label className="flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={value.planner}
              disabled={disabled}
              onChange={(event) =>
                onChange({ ...value, planner: event.target.checked })
              }
              className="h-3.5 w-3.5 rounded border-line-strong text-accent"
            />
            <span className="text-ink">Model picks the tools</span>
            <span className="text-ink-subtle">
              off = chosen by rule, one pass, no retry
            </span>
          </label>

          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-ink-subtle">
              <Wrench className="h-3 w-3" />
              Extra tools
            </p>

            <div className="flex flex-wrap gap-1.5">
              {tools.map((one) => {
                const on = (value.tools ?? []).includes(one.id)

                return (
                  <button
                    key={one.id}
                    type="button"
                    onClick={() => toggleTool(one.id)}
                    disabled={disabled || !one.enabled}
                    aria-pressed={on}
                    title={
                      one.enabled
                        ? one.description
                        : `${one.description} Currently switched off server-side.`
                    }
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition-colors',
                      on
                        ? 'border-accent/50 bg-accent-soft text-ink'
                        : 'border-line text-ink-muted hover:bg-raised hover:text-ink',
                      !one.enabled && 'cursor-not-allowed opacity-40',
                    )}
                  >
                    {one.label}
                    {!one.enabled && ' (off)'}
                  </button>
                )
              })}
            </div>

            <p className="mt-1.5 text-2xs leading-4 text-ink-subtle">
              Search tools come from the retrievers above — turning the
              agent on never widens what is searched.
            </p>
          </div>
        </div>
      )}

      {!empty && (
        <p className="mt-2 flex flex-wrap items-center gap-1 text-2xs text-ink-subtle">
          {value.agent && <Badge tone="neutral">agent</Badge>}
          <span className="tnum">{describe(value)}</span>
        </p>
      )}
    </div>
  )
}

/** The composition as one line, matching the id the server will record. */
export function describe(value) {
  const order = ['semantic', 'keyword', 'hierarchical']

  const base = order.filter((one) => value.retrievers.includes(one)).join(' + ')

  if (!value.agent) return base

  const extras = (value.tools ?? []).length
    ? ` + ${(value.tools ?? []).join(', ')}`
    : ''

  return `agent${value.planner ? '' : ' (direct)'} over ${base}${extras}`
}
