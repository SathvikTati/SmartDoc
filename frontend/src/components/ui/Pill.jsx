import { cn } from '@/lib/format'

/**
 * A fully-rounded outline control.
 *
 * Distinct from `Button` on purpose: pills are the light, secondary
 * controls that sit *inside* a composer or under it as suggestions, where
 * a squared button would read as the primary action.
 */
export function Pill({
  as: Component = 'button',
  active = false,
  className,
  children,
  ...props
}) {
  return (
    <Component
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5',
        'text-sm transition-colors duration-100 whitespace-nowrap',
        'disabled:opacity-50 disabled:pointer-events-none',
        active
          ? 'border-accent/30 bg-accent-soft text-accent'
          : 'border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink',
        className,
      )}
      {...(Component === 'button' ? { type: 'button' } : {})}
      {...props}
    >
      {children}
    </Component>
  )
}

/** The one filled, high-emphasis action in a composer. */
export function PillButton({ className, children, loading, disabled, ...props }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center gap-2 rounded-full px-5 py-2',
        'bg-accent text-sm font-medium text-white',
        'transition-colors duration-100 hover:bg-accent-hover',
        'disabled:opacity-40 disabled:pointer-events-none',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
