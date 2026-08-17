import { cn } from '@/lib/format'

/**
 * A bordered region. Used for tables and evidence lists — not as a wrapper
 * around every stray paragraph, which is how a page turns into a card
 * gallery.
 */
export function Panel({ className, children }) {
  return (
    <div
      className={cn(
        'rounded-md border border-line bg-surface shadow-panel',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function PanelHeader({ title, meta, actions, className }) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-b border-line px-3 py-2',
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <h2 className="truncate text-sm font-medium text-ink">{title}</h2>
        {meta && <span className="text-xs text-ink-subtle">{meta}</span>}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
      )}
    </div>
  )
}

/**
 * A plain section heading with a hairline rule. The default way to separate
 * content on a page — reach for `Panel` only when the content is a list or
 * table that benefits from being visually contained.
 */
export function SectionHeading({ title, meta, actions, className }) {
  return (
    <div className={cn('mb-3 border-b border-line pb-2', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-medium tracking-tight text-ink">
            {title}
          </h2>
          {meta && <span className="text-xs text-ink-subtle">{meta}</span>}
        </div>
        {actions && <div className="flex items-center gap-1.5">{actions}</div>}
      </div>
    </div>
  )
}
