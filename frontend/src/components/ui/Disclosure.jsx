import { useState } from 'react'
import { ChevronRight } from 'lucide-react'

import { cn } from '@/lib/format'

/**
 * Collapsible region with a real button trigger. Retrieval detail lives
 * behind these: inspectable on demand, never hidden outright, and never
 * expanded by default into a wall of numbers.
 */
export function Disclosure({
  title,
  meta,
  defaultOpen = false,
  bordered = true,
  children,
  className,
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div
      className={cn(
        bordered && 'rounded-md border border-line bg-surface',
        className,
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          'text-sm font-medium text-ink transition-colors hover:bg-raised',
          bordered && 'rounded-md',
          open && bordered && 'rounded-b-none border-b border-line',
        )}
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-ink-subtle transition-transform duration-150',
            open && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {meta && (
          <span className="shrink-0 text-xs font-normal text-ink-subtle">
            {meta}
          </span>
        )}
      </button>

      {open && <div className="animate-fade-in">{children}</div>}
    </div>
  )
}
