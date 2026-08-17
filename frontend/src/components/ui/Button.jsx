import { forwardRef } from 'react'
import { Loader2 } from 'lucide-react'

import { cn } from '@/lib/format'

const VARIANTS = {
  primary:
    'bg-accent text-white border border-accent hover:bg-accent-hover hover:border-accent-hover',
  default:
    'bg-surface text-ink border border-line hover:bg-raised hover:border-line-strong',
  ghost:
    'bg-transparent text-ink-muted border border-transparent hover:bg-raised hover:text-ink',
  danger:
    'bg-surface text-danger border border-line hover:bg-danger-soft hover:border-danger/30',
}

const SIZES = {
  sm: 'h-7 px-2.5 text-xs gap-1.5',
  md: 'h-8 px-3 text-sm gap-2',
}

export const Button = forwardRef(function Button(
  {
    variant = 'default',
    size = 'md',
    loading = false,
    className,
    children,
    disabled,
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center rounded font-medium',
        'transition-colors duration-100 whitespace-nowrap',
        'disabled:opacity-50 disabled:pointer-events-none',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  )
})
